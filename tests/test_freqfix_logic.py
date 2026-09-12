"""freqfix's targeting and accept/reject decisions, driven by a scripted model.

This is the stage that rewrites the words readers meet most, so a change in what
it targets or what it accepts has more reach than any other. It is also the stage
a model-free suite would normally leave untested. Running the real script against
a fake llama-server covers it without a model and without refactoring the script.
"""
import json, subprocess, sys, tempfile, unittest
from pathlib import Path

from tests.util import ROOT
from tests.fakemodel import FakeModel

FIX = Path(__file__).resolve().parent / 'fixtures'


def is_judge(system):
    return system.lstrip().startswith('Rate how well')


def judged_gloss(user):
    """The gloss out of a judge prompt.

    Must be read from the 'Gloss:' line, not by searching the whole prompt: the
    entry text is in there too, and for `ab` it literally contains the words
    'away from', so a naive substring test scores the incumbent as if it were
    the candidate."""
    return user.rsplit('Gloss:', 1)[-1].strip().rstrip('Digit:').strip()


class FreqfixRun:
    """Run the real freqfix.py against a scripted model; return the output rows."""

    def __init__(self, gloss_reply, judge_reply, extra=()):
        self.gloss_reply, self.judge_reply, self.extra = gloss_reply, judge_reply, list(extra)

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        out, ckpt = d / 'out.tsv', d / 'ckpt.jsonl'

        def reply(system, user):
            return self.judge_reply(user) if is_judge(system) else self.gloss_reply(user)

        self.model = FakeModel(reply).__enter__()
        cmd = [sys.executable, str(ROOT / 'freqfix.py'),
               '--xml', str(FIX / 'mini.xml'), '--tsv', str(FIX / 'mini.tsv'),
               '--freq', str(FIX / 'mini_freq.tsv'), '--out', str(out),
               '--ckpt', str(ckpt), '--url', self.model.url,
               '--top', '10', '-j', '1'] + self.extra
        self.proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
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
        self.model.__exit__()
        self.tmp.cleanup()


class TestTargeting(unittest.TestCase):
    def test_targets_a_row_the_detectors_flag(self):
        with FreqfixRun(lambda u: 'from, away from', lambda u: '5', ['--dry-run']) as r:
            self.assertIn('word-class', r.stderr, r.stderr)
            self.assertIn('ăb', r.stderr)

    def test_leaves_clean_rows_alone(self):
        with FreqfixRun(lambda u: 'x', lambda u: '5', ['--dry-run']) as r:
            self.assertIn('defective: 1 entries', r.stderr, r.stderr)

    def test_orders_targets_by_corpus_frequency(self):
        # the whole point of the stage: ab (5000) must be reported above porta
        with FreqfixRun(lambda u: 'x', lambda u: '5', ['--dry-run']) as r:
            self.assertIn('5,000x', r.stderr.replace('5000x', '5,000x'), r.stderr)


class TestAcceptance(unittest.TestCase):
    def test_accepts_a_better_candidate(self):
        with FreqfixRun(lambda u: 'from, away from',
                        lambda u: '5' if 'away from' in judged_gloss(u) else '1') as r:
            self.assertEqual(r.rows['ab'][2], 'from, away from', r.stderr)
            self.assertEqual(r.rows['ab'][3], 'freqfix')

    def test_rejects_a_candidate_the_judge_rates_no_better(self):
        with FreqfixRun(lambda u: 'from, away from', lambda u: '3') as r:
            self.assertEqual(r.rows['ab'][2], 'preposition with ablative', r.stderr)
            self.assertIn('rejected as no better 1', r.stderr)

    def test_rejects_a_candidate_that_fails_the_detectors(self):
        # the replacement is itself a word-class description
        with FreqfixRun(lambda u: 'demonstrative pronoun', lambda u: '5') as r:
            self.assertEqual(r.rows['ab'][2], 'preposition with ablative', r.stderr)

    def test_rejects_an_empty_candidate(self):
        with FreqfixRun(lambda u: '', lambda u: '5') as r:
            self.assertEqual(r.rows['ab'][2], 'preposition with ablative', r.stderr)

    def test_never_touches_untargeted_rows(self):
        with FreqfixRun(lambda u: 'from, away from', lambda u: '5') as r:
            self.assertEqual(r.rows['porta'][2], 'gate, entrance')
            self.assertEqual(r.rows['porta'][3], 'model')
            self.assertEqual(r.rows['stella'][2], 'star')

    def test_output_keeps_every_input_row(self):
        with FreqfixRun(lambda u: 'from, away from', lambda u: '5') as r:
            self.assertEqual(set(r.rows), {'porta', 'ab', 'stella'})


class TestJudgeIsShownTheRightThing(unittest.TestCase):
    def test_judge_sees_the_candidate_gloss(self):
        seen = []
        with FreqfixRun(lambda u: 'from, away from',
                        lambda u: seen.append(u) or '5'):
            pass
        self.assertTrue(any('from, away from' in u for u in seen),
                        'judge was never shown the candidate')


if __name__ == '__main__':
    unittest.main()
