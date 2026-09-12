"""xrefix.py: the repair stage for cross-reference part-of-speech mismatch and
for entries with no gloss.

The stage it replaces ("adapt") measured WORSE than doing nothing, because it
rewrote every cross-reference and kept whatever came back. These tests pin the
two things that make this version different: it only targets a measured
mismatch, and a replacement has to clear an absolute quality bar. If either
regresses, the whole stage goes back to being net-negative.
"""
import subprocess, sys, tempfile, unittest
from pathlib import Path

from tests.util import ROOT
from tests.fakemodel import FakeModel

FIX = Path(__file__).resolve().parent / 'fixtures'


def judged_gloss(user):
    return user.rsplit('CANDIDATE GLOSS:', 1)[-1].rsplit('Score:', 1)[0].strip()


class Run:
    def __init__(self, adapt, repair, judge, extra=()):
        self.adapt, self.repair, self.judge, self.extra = adapt, repair, judge, list(extra)

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        out = d / 'o.tsv'

        def reply(system, user):
            if system.lstrip().startswith('You grade'):
                return self.judge(judged_gloss(user))
            if 'cross-reference' in system:
                return self.adapt(user)
            return self.repair(user)

        self.model = FakeModel(reply).__enter__()
        self.proc = subprocess.run(
            [sys.executable, str(ROOT / 'xrefix.py'),
             '--xml', str(FIX / 'mini_xref.xml'), '--tsv', str(FIX / 'mini_xref.tsv'),
             '--out', str(out), '--ckpt', str(d / 'c.jsonl'),
             '--url', self.model.url, '-j', '1'] + self.extra,
            capture_output=True, text=True, timeout=120)
        self.stderr = self.proc.stderr
        self.rows = {}
        if out.exists():
            for line in out.read_text(encoding='utf-8').splitlines():
                if line.startswith('#'):
                    continue
                f = line.split('\t')
                if len(f) >= 4:
                    self.rows[f[0]] = f
        return self

    def __exit__(self, *a):
        self.model.__exit__(); self.tmp.cleanup()


class TestSelection(unittest.TestCase):
    def test_targets_the_pos_mismatch_and_the_empty_row(self):
        with Run(lambda u: 'x', lambda u: 'x', lambda g: '5', ['--dry-run']) as r:
            self.assertIn('empty=1', r.stderr, r.stderr)
            self.assertIn('pos-mismatch=1', r.stderr)

    def test_does_not_target_a_matching_cross_reference(self):
        # stella and verus are not cross-references and must never be touched
        with Run(lambda u: 'x', lambda u: 'x', lambda g: '5', ['--dry-run']) as r:
            self.assertNotIn('stella', r.stderr)
            self.assertIn('targets: 2', r.stderr)


class TestAcceptance(unittest.TestCase):
    GOOD_ADAPT = staticmethod(lambda u: 'in truth, certainly')
    GOOD_FILL = staticmethod(lambda u: 'small sea vessel')

    def test_accepts_an_adapted_gloss_the_judge_rates_well(self):
        with Run(self.GOOD_ADAPT, self.GOOD_FILL,
                 lambda g: '5' if 'truth' in g or 'vessel' in g else '2') as r:
            self.assertEqual(r.rows['vero'][2], 'in truth, certainly', r.stderr)
            self.assertEqual(r.rows['vero'][3], 'xrefix')

    def test_fills_an_empty_gloss(self):
        with Run(self.GOOD_ADAPT, self.GOOD_FILL,
                 lambda g: '5' if 'truth' in g or 'vessel' in g else '2') as r:
            self.assertEqual(r.rows['blankus'][2], 'small sea vessel', r.stderr)
            self.assertEqual(r.rows['blankus'][3], 'refilled')

    def test_rejects_a_candidate_below_the_absolute_bar(self):
        # the incumbent is bad, but "better than bad" is not good enough
        with Run(self.GOOD_ADAPT, self.GOOD_FILL, lambda g: '3') as r:
            self.assertEqual(r.rows['vero'][2], 'true, real, genuine', r.stderr)
            self.assertEqual(r.rows['vero'][3], 'xref-resolved')

    def test_rejects_a_candidate_that_fails_the_detectors(self):
        with Run(lambda u: 'demonstrative pronoun', self.GOOD_FILL, lambda g: '5') as r:
            self.assertEqual(r.rows['vero'][2], 'true, real, genuine', r.stderr)

    def test_rejects_an_empty_candidate(self):
        with Run(lambda u: '', lambda u: '', lambda g: '5') as r:
            self.assertEqual(r.rows['vero'][2], 'true, real, genuine')
            self.assertEqual(r.rows['blankus'][2], '')

    def test_does_not_replace_a_gloss_the_judge_rates_no_better(self):
        with Run(self.GOOD_ADAPT, self.GOOD_FILL, lambda g: '4') as r:
            # incumbent also scores 4, so the challenger must not win on a tie
            self.assertEqual(r.rows['vero'][2], 'true, real, genuine', r.stderr)

    def test_never_touches_untargeted_rows(self):
        with Run(self.GOOD_ADAPT, self.GOOD_FILL, lambda g: '5') as r:
            self.assertEqual(r.rows['stella'][2], 'star')
            self.assertEqual(r.rows['verus'][2], 'true, real, genuine')
            self.assertEqual(r.rows['stella'][3], 'model')

    def test_output_keeps_every_row(self):
        with Run(self.GOOD_ADAPT, self.GOOD_FILL, lambda g: '5') as r:
            self.assertEqual(set(r.rows), {'verus', 'vero', 'blankus', 'stella'})


class TestCoinageFilter(unittest.TestCase):
    """Adapting an adverb invites coinage; L&S's own English is the wordlist."""

    def test_rejects_a_coined_adverb(self):
        # 'gloriously' would be fine; 'bodilyly' is not a word
        with Run(lambda u: 'bodilyly', lambda u: 'small sea vessel', lambda g: '5') as r:
            self.assertEqual(r.rows['vero'][2], 'true, real, genuine', r.stderr)

    def test_accepts_a_real_adverb(self):
        with Run(lambda u: 'truly, certainly', lambda u: 'small sea vessel',
                 lambda g: '5' if 'truly' in g or 'vessel' in g else '2') as r:
            self.assertEqual(r.rows['vero'][2], 'truly, certainly', r.stderr)


class TestPosMarker(unittest.TestCase):
    def test_reads_the_headword_line_only(self):
        # the marker xrefix selects on lives in common.py, shared with lsgloss
        from common import pos_marker
        self.assertEqual(pos_marker('vērō, adv., v. verus.'), 'adv')
        self.assertEqual(pos_marker('vērus, a, um, adj. true'), 'adj')
        self.assertEqual(pos_marker('porta, ae, f. a gate' + ' x' * 100 + ' adv.'), None)


if __name__ == '__main__':
    unittest.main()
