"""One executable spec per defect in REVIEW.md.

Every test here FAILS today and is marked expectedFailure, so the suite is green
against current code. When a fix lands, unittest reports the test as an
UNEXPECTED SUCCESS -- which fails the run -- forcing whoever fixed it to delete
the marker. That is the point: the spec cannot be quietly left behind by the fix,
and the fix cannot be declared done without something asserting it.

Delete the @unittest.expectedFailure line as each one is fixed. Nothing else here
should need to change.
"""
import subprocess, sys, tempfile, unittest
from pathlib import Path

from tests.util import ROOT
from tests.fakemodel import FakeModel
from clean_gloss import clean, enforce
from suspect import reasons
from inflect import forms_for, _noun_stem_and_key
from lemmafreq import lemma_frequencies
from common import fold

FIX = Path(__file__).resolve().parent / 'fixtures'

PREP_ENTRY = ('ăb, ā, abs, praep. with abl. In general it denotes departure '
              'from a fixed point, from, away from, out of')


# ---------------------------------------------------------------- finding 1
class TestMetalinguisticGloss(unittest.TestCase):
    """A description of a word's grammatical ROLE is not a gloss.

    POSDESC is anchored with ^ and only matches a bare part-of-speech noun, so
    every phrasing below passes every detector today. These are the highest-token
    defects in the corpus.

    PARTLY FIXED: POSWORD/FRAME now fire, but only when the ENTRY is itself a
    function word (OWNPOS) -- ungated they flag "to mark out" and "glittering
    particle". 10 rows, 223,056 tokens. See the first test for what is still open.
    """

    @unittest.expectedFailure
    def test_flags_departure_from_a_fixed_point(self):
        # STILL OPEN, and probably not fixable with a detector. This gloss names
        # no word class and uses no metalinguistic verb; it is an ordinary English
        # noun phrase that happens to describe what the preposition denotes. The
        # rules that would catch it -- "a function word's gloss should not head on
        # a content noun" -- flag `sed` -> "but, yet, except" and `per` ->
        # "through, across, throughout", which are correct. Measured over the
        # corpus that rule produced ~75 false positives against a handful of true
        # ones, so it is deliberately not implemented: routing 75 correct glosses
        # to re-glossing is a worse trade than missing this one. Needs the prompt
        # rule plus a judge, not a mechanical check.
        self.assertIn('word-class',
                      reasons('ăb', 'departure from a fixed point', 'freqfix', PREP_ENTRY))

    def test_flags_example_introducer(self):
        self.assertIn('word-class',
                      reasons('quĭdem', 'example introducer', 'freqfix',
                              'quidem, adv. indeed, certainly'))

    def test_flags_to_introduce_an_explanation(self):
        self.assertIn('word-class',
                      reasons('nam', 'to introduce an explanation', 'freqfix',
                              'nam, conj. for, for indeed'))

    def test_flags_a_word_class_named_late_in_the_gloss(self):
        self.assertIn('word-class',
                      reasons('nĕc', 'inseparable negative particle', 'hard',
                              'nec, conj. and not, nor'))

    def test_does_not_flag_a_real_function_word_gloss(self):
        # guard against the fix over-firing: these must stay clean
        for g in ('from, away from', 'and', 'out of, from', 'not', 'indeed, certainly'):
            with self.subTest(g):
                self.assertNotIn('word-class', reasons('x', g, 'model', PREP_ENTRY))


# ---------------------------------------------------------------- finding 2
class TestPosParenthetical(unittest.TestCase):
    """clean() strips '(verb)' and '(noun)' but not '(conjunction)'.

    FIXED: POSNOTE now covers the function-word classes and an optional
    qualifier. Six rows across the raw-reply corpus, including `et`.
    """

    def test_strips_conjunction(self):
        self.assertEqual(clean('and (conjunction)'), 'and')

    def test_strips_preposition(self):
        self.assertEqual(clean('from (preposition)'), 'from')

    def test_strips_pronoun(self):
        self.assertEqual(clean('self (reflexive pronoun)'), 'self')

    def test_still_keeps_register_labels(self):
        # guard: "(post-Aug.)" is not a part of speech and must survive
        self.assertEqual(clean('lameness, limping (post-Aug.)'),
                         'lameness, limping (post-Aug.)')


# --------------------------------------------------------------- finding 3a
class TestHomographFrequency(unittest.TestCase):
    """Homographs shared one frequency, so freqfix screened the same stem 16 times.

    L&S numbers homographs off a shared stem, but `in1` is the preposition while
    `in3` is *in-actuosus* -- a different word entirely. Collapsing them onto the
    key `in` and taking the max handed the rare adjective the preposition's whole
    corpus count.

    FIXED: lemma_frequencies is keyed per entry, and no longer injects the
    digit-stripped key into the form set.
    """

    ROWS = [['in1', 'in', 'in, within', 'model'],
            ['in3', 'ĭn-actŭōsus', 'inactive', 'model']]
    BODIES = ['in, praep. in, within',
              'in-actuosus, a, um, adj. inactive']

    def test_a_rare_homograph_does_not_inherit_the_common_one(self):
        lf = lemma_frequencies(self.ROWS, self.BODIES, {'in': 137460})
        self.assertEqual(lf.get('in1'), 137460)
        self.assertNotEqual(lf.get('in3'), 137460)


# --------------------------------------------------------------- finding 3b
class TestAbbreviatedGenitive(unittest.TestCase):
    """`Spāco, cūs` means Spa-cūs. The us/is branches ignore the `abbreviated`
    guard that the i/ae branches apply, so the stem becomes `c`.
    FIXED: the us/is branches now consult `abbreviated` like the i/ae ones.
    """

    def test_spaco_does_not_stem_to_c(self):
        stem, key = _noun_stem_and_key('Spāco', 'cūs')
        self.assertNotEqual(stem, 'c')

    def test_spaco_does_not_generate_cum(self):
        f = forms_for('Spāco', 'Spāco, cūs, f., the nurse of Cyrus')
        self.assertNotIn('cum', f)
        self.assertNotIn('cui', f)

    def test_a_full_genitive_still_works(self):
        # guard: manus, us must keep its paradigm
        self.assertLessEqual({'manus', 'manui', 'manuum'},
                             forms_for('manus', 'manus, us, f. a hand'))


# ---------------------------------------------------------------- finding 5
class TestEtymologyLeak(unittest.TestCase):
    """`vel` is glossed with the meaning of *volo*, the word it derives from."""

    ENTRY = ('vel, conj. [from volo, to will, to choose] or, or else, '
             'introducing an alternative')

    @unittest.expectedFailure
    def test_flags_a_gloss_taken_from_the_etymology(self):
        self.assertTrue(reasons('vel', 'to choose, prefer', 'model', self.ENTRY),
                        'gloss is the etymon meaning, not the word meaning')


# ---------------------------------------------------------------- finding 6
class TestLeadingHeadwordEcho(unittest.TestCase):
    """A gloss that opens by repeating the Latin headword wastes its first word.

    PARTLY FIXED: suspect.gloss_vocabulary + the `head-echo` reason catch 59 rows
    (15,067 tokens) -- every case where no OTHER entry uses the word in a gloss,
    which is good evidence it is Latin rather than English.
    """

    def test_flags_verum_glossed_verum_true_real(self):
        from suspect import gloss_vocabulary
        vocab = gloss_vocabulary([['verum', 'vērum', 'verum, true, real, genuine', 'model']])
        self.assertIn('head-echo',
                      reasons('vērum', 'verum, true, real, genuine', 'model',
                              'verum, i, n. truth', vocab))

    @unittest.expectedFailure
    def test_flags_tamen_glossed_tamen_nevertheless(self):
        # STILL OPEN. `tamen` is used in one other entry's gloss (attamen, which
        # inherits it by cross-reference), so the vocabulary test reads it as
        # English. Loosening the threshold to catch it also catches `angina`,
        # `inertia` and `squalor` -- real English loanwords that happen to be rare
        # in the gloss corpus. Since lsgloss.py's hard pass accepts a replacement
        # without a score gate, a false positive there can come back WORSE, so the
        # conservative threshold is deliberate. Needs an English wordlist.
        from suspect import gloss_vocabulary
        vocab = gloss_vocabulary([['attamen', 'attămen', 'tamen, nevertheless', 'model']])
        self.assertIn('head-echo',
                      reasons('tămen', 'tamen, nevertheless, however, still', 'model',
                              'tamen, adv. nevertheless, however', vocab))

    def test_does_not_flag_a_genuine_english_cognate(self):
        # guard: these are correct and must not be rewritten
        for head, gloss in (('orator', 'speaker, orator'),
                            ('victor', 'conqueror, victor'),
                            ('in', 'in, within, on, upon')):
            with self.subTest(head):
                self.assertNotIn('bare-echo',
                                 reasons(head, gloss, 'model', f'{head}, a word'))


# ---------------------------------------------------------------- finding 7
class TestFreqfixJudgesTheIncumbentFairly(unittest.TestCase):
    """decide() scores the incumbent against the CHALLENGER's window.

    A correct incumbent whose supporting text sits at the start of the entry is
    judged against a window 3,200 characters in, where nothing supports it, so it
    loses to whatever the model just produced. The comparison must give each gloss
    its own best window.
    """

    def _run(self):
        seen = []
        tmp = tempfile.TemporaryDirectory()
        d = Path(tmp.name)

        def reply(system, user):
            if system.lstrip().startswith('Rate how well'):
                entry, _, gloss = user.rpartition('Gloss:')
                gloss = gloss.strip().rstrip('Digit:').strip()
                seen.append((entry, gloss))
                key = gloss.split(',')[0].split()[0].lower() if gloss.split() else ''
                return '5' if key and key in entry.lower() else '1'
            return 'departure from a fixed point'

        with FakeModel(reply) as m:
            subprocess.run(
                [sys.executable, str(ROOT / 'freqfix.py'),
                 '--xml', str(FIX / 'mini_long.xml'), '--tsv', str(FIX / 'mini_long.tsv'),
                 '--freq', str(FIX / 'mini_long_freq.tsv'),
                 '--out', str(d / 'o.tsv'), '--ckpt', str(d / 'c.jsonl'),
                 '--url', m.url, '--top', '10', '-j', '1'],
                capture_output=True, text=True, timeout=180)
        tmp.cleanup()
        return seen

    def test_incumbent_is_judged_against_the_start_of_its_entry(self):
        seen = self._run()
        incumbent = [entry for entry, gloss in seen if gloss == 'preposition with ablative']
        self.assertTrue(incumbent, 'the incumbent was never judged at all')
        self.assertTrue(any('gate' in e for e in incumbent),
                        'the incumbent was only ever judged against the '
                        "challenger's window, never against the start of its entry")


# --------------------------------------------------------------- new bug 1
class TestEnforceLeavesNoDanglingArticle(unittest.TestCase):
    """The _contentless fallback swaps one bad output for another.

    'one who is of the household' -> 'one who is of the': the guard rejects the
    contentless cut, then falls back to a hard slice that ends on an article.

    FIXED: _undangle now runs on every fallback path, not only the first cut.
    Three entries affected.
    """

    def test_does_not_end_on_an_article(self):
        got = enforce('one who is of the household', 5)
        self.assertNotIn(got.split()[-1].lower(), {'the', 'a', 'an', 'of', 'to'},
                         f'dangling function word in {got!r}')


# --------------------------------------------------------------- new bug 2
class TestFifthDeclension(unittest.TestCase):
    """The 'ei' paradigm branch is unreachable.

    `endswith('i')` catches `rei` first and inflects *res* as 2nd declension, so
    it generates reus/reum/reo (real forms of *reus*, 'defendant') and never
    generates rem/rebus/rerum -- 20,162 corpus tokens.
    
    FIXED: the -ei test now runs before the -i test that was shadowing it.
    """

    def test_res_generates_its_real_forms(self):
        f = forms_for('res', 'res, rei, f. a thing, an object')
        self.assertLessEqual({'rem', 'rebus', 'rerum'}, f)

    def test_res_does_not_claim_the_paradigm_of_reus(self):
        f = forms_for('res', 'res, rei, f. a thing, an object')
        self.assertNotIn('reus', f)
        self.assertNotIn('reum', f)

    def test_the_fifth_declension_branch_is_reachable(self):
        self.assertEqual(_noun_stem_and_key('res', 'rei'), ('r', 'ei'))


# --------------------------------------------------------------- new bug 3
class TestVerbEndingsAreFolded(unittest.TestCase):
    """The stem is folded but the ending tables are not.

    VERB['are'] carries 'avi', 'avit', 'averunt' and VERB['ire'] carries 'ivi',
    'ivit', 'iverunt'. A corpus form folds v->u, so amavit in a text is amauit and
    never matches the generated amavit: 20,835 dead forms, 13,825 recoverable
    tokens.

    FIXED: forms_for now folds at the boundary, so the tables can stay in
    conventional spelling. Recovered 13,825 corpus tokens.
    """

    def test_first_conjugation_perfect_is_folded(self):
        f = forms_for('amo', 'amo, avi, atum, 1, v. a. to love')
        self.assertIn('amauit', f)

    def test_fourth_conjugation_perfect_is_folded(self):
        f = forms_for('audio', 'audio, ivi, itum, 4, v. a. to hear')
        self.assertIn('audiuit', f)

    def test_no_generated_form_is_half_folded(self):
        f = forms_for('amo', 'amo, avi, atum, 1, v. a. to love')
        bad = sorted(w for w in f if fold(w) != w)
        self.assertEqual(bad, [], f'unfoldable forms can never match: {bad}')


if __name__ == '__main__':
    unittest.main()
