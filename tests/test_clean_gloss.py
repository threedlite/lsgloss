"""clean() and enforce() are the last thing to touch every gloss.

They run after every model pass, so a change here rewrites the whole corpus at
once. Each case below is a behaviour the README or a code comment names as
deliberate; several encode a bug that was fixed once and must not come back.
"""
import unittest
from tests.util import ROOT
from clean_gloss import clean, enforce


class TestCitationStripping(unittest.TestCase):
    """Citations are stripped; register labels are kept."""

    def test_strips_author_and_numbers(self):
        self.assertEqual(clean('raven-black color, Vitr. 8, 3'), 'raven-black color')

    def test_strips_section_sign(self):
        self.assertEqual(clean('white, viscous matter § 31'), 'white, viscous matter')

    def test_strips_q_v(self):
        self.assertEqual(clean('to cast away, throw down q. v.'), 'to cast away')

    def test_keeps_register_label(self):
        # "(post-Aug.)" is information about the sense, not a citation
        self.assertEqual(clean('lameness, limping (post-Aug.)'),
                         'lameness, limping (post-Aug.)')


class TestPartOfSpeechNotes(unittest.TestCase):
    def test_strips_bare_pos_annotation(self):
        self.assertEqual(clean('box (verb)'), 'box')
        self.assertEqual(clean('shoot (noun)'), 'shoot')


class TestExampleMarkers(unittest.TestCase):
    """An example marker introduces a citation; a restatement marker does not."""

    def test_cuts_at_e_g(self):
        # ("Roman nomen" is itself rendered "Roman family name"; see NAME_RENDER)
        self.assertEqual(clean('Roman nomen, e.g'), 'Roman family name')
        self.assertEqual(clean('Roman surname, e.g. consul'), 'Roman surname')

    def test_cuts_at_cf(self):
        self.assertEqual(clean('shield, cf. clipeus'), 'shield')

    def test_keeps_i_e_because_it_restates_the_sense(self):
        # cutting here loses real content: "abjuring, i.e. resigning, abdication"
        self.assertTrue(clean('abjuring, i.e. resigning').startswith('abjuring, i.e.'))


class TestArticlesAndDangles(unittest.TestCase):
    def test_drops_leading_article(self):
        self.assertEqual(clean('a little star'), 'little star')

    def test_never_strips_a_complete_gloss_to_nothing(self):
        # "and" and "out of, from" are complete glosses for function words
        self.assertEqual(clean('and'), 'and')
        self.assertEqual(clean('out of, from'), 'out of, from')

    def test_keeps_natural_phrasing(self):
        # a comma must not be forced where "of" is the right word
        self.assertEqual(clean('stamping of money'), 'stamping of money')


class TestRepetitionCollapse(unittest.TestCase):
    def test_cuts_at_first_repeated_ngram(self):
        # greedy decoding sometimes loops
        self.assertEqual(clean('to sharpen to sharpen'), 'to sharpen')

    def test_leaves_genuine_repetition_of_one_word_alone(self):
        self.assertEqual(clean('little by little'), 'little by little')


class TestEnforceWordCap(unittest.TestCase):
    def test_under_cap_is_untouched(self):
        self.assertEqual(enforce('little star', 5), 'little star')

    def test_cuts_at_a_phrase_boundary_not_mid_phrase(self):
        self.assertEqual(enforce('city on the borders of the sea', 5),
                         'city on the borders')

    def test_never_ends_on_a_dangling_preposition(self):
        got = enforce('city on the borders of the sea', 5)
        self.assertNotIn(got.split()[-1].lower(), {'of', 'on', 'the', 'a', 'an', 'to'})

    def test_drops_leading_preposition_to_keep_the_informative_tail(self):
        # "of the colour of myrtle-berries" must not truncate to "of the colour"
        got = enforce('of the colour of myrtle-berries', 5)
        self.assertIn('myrtle-berries', got)


class TestIdempotence(unittest.TestCase):
    """Both run more than once over the same text in the real pipeline
    (finalise() is called twice), so neither may drift on a second pass."""

    CASES = ['raven-black color, Vitr. 8, 3', 'a little star', 'and',
             'lameness, limping (post-Aug.)', 'of the colour of myrtle-berries',
             'city on the borders of the sea', 'to sharpen to sharpen', 'box (verb)']

    def test_clean_is_idempotent(self):
        for c in self.CASES:
            with self.subTest(c):
                self.assertEqual(clean(clean(c)), clean(c))

    def test_enforce_is_idempotent(self):
        for c in self.CASES:
            with self.subTest(c):
                e = enforce(clean(c), 5)
                self.assertEqual(enforce(e, 5), e)

    def test_enforce_respects_the_cap(self):
        for c in self.CASES:
            with self.subTest(c):
                self.assertLessEqual(len(enforce(clean(c), 5).split()), 5)


if __name__ == '__main__':
    unittest.main()
