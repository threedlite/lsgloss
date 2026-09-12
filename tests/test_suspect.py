"""The mechanical detectors decide which glosses get re-asked.

They are the gate in front of every repair stage, so a detector that stops
firing does not raise -- it just quietly stops repairing that class, and the
defect ships. Each detector below is tested for what it must catch AND for what
it must not, because a false positive here rewrites correct glosses.
"""
import unittest
from tests.util import ROOT
from suspect import reasons

NOUN_ENTRY = 'stellŭla, ae, f. dim. a little star, a small star'
PREP_ENTRY = 'ăb, ā, abs, praep. with abl. from, away from'


def why(head, gloss, source='model', entry=NOUN_ENTRY):
    return reasons(head, gloss, source, entry)


class TestUngrounded(unittest.TestCase):
    def test_flags_a_gloss_with_no_word_from_the_entry(self):
        self.assertIn('ungrounded', why('stellŭla', 'winged horse'))

    def test_does_not_flag_a_gloss_taken_from_the_entry(self):
        self.assertNotIn('ungrounded', why('stellŭla', 'little star'))

    def test_exempts_function_words(self):
        # a pronoun's English gloss will not appear in Latin entry text, so
        # grounding cannot apply; see FUNCTION_ENTRY
        self.assertNotIn('ungrounded', why('ăb', 'from, away from', entry=PREP_ENTRY))

    def test_exempts_cross_references(self):
        # an inherited gloss legitimately takes its wording from the target entry
        self.assertNotIn('ungrounded', why('x', 'winged horse', source='xref-resolved'))


class TestWordClass(unittest.TestCase):
    def test_flags_a_part_of_speech_as_a_gloss(self):
        self.assertIn('word-class', why('ăb', 'preposition with ablative', entry=PREP_ENTRY))
        self.assertIn('word-class', why('ille', 'demonstrative pronoun', entry=PREP_ENTRY))

    def test_does_not_flag_a_real_gloss(self):
        self.assertNotIn('word-class', why('ăb', 'from, away from', entry=PREP_ENTRY))


class TestLatinChars(unittest.TestCase):
    def test_flags_macrons_left_in_the_gloss(self):
        self.assertIn('latin-chars', why('x', 'stellŭla'))

    def test_flags_greek(self):
        self.assertIn('latin-chars', why('x', 'from Σπακώ'))

    def test_plain_english_passes(self):
        self.assertNotIn('latin-chars', why('stellŭla', 'little star'))


class TestBareEcho(unittest.TestCase):
    def test_flags_the_headword_as_its_own_gloss(self):
        self.assertIn('bare-echo', why('Melos', 'Melos'))

    def test_flags_headword_plus_declension_ending(self):
        self.assertIn('bare-echo', why('Melos', 'Melos, i'))

    def test_does_not_flag_a_gloss_that_merely_contains_the_headword(self):
        # "orator -> speaker, orator" is a correct English gloss
        self.assertNotIn('bare-echo', why('orator', 'speaker, orator'))


class TestFragment(unittest.TestCase):
    def test_flags_a_truncation_fragment(self):
        self.assertIn('fragment', why('x', 'one who is'))

    def test_does_not_flag_a_real_function_word_gloss(self):
        # "out of, from" is a complete gloss for a preposition
        self.assertNotIn('fragment', why('ex', 'out of, from', entry=PREP_ENTRY))


class TestEtymologyLeak(unittest.TestCase):
    """In this revision the etymon is often unbracketed, right after the gender:
    "pĭĕtas, ātis, f. pius, dutiful conduct" -- and the model glosses it "pius"."""

    PIETAS = 'pĭĕtas, ātis, f. pius, dutiful conduct towards the gods, sense of duty'
    HUMANO = 'hūmāno, āvi, ātum, 1 humanus, to make human'

    def test_flags_a_one_word_gloss_that_is_the_etymon(self):
        self.assertIn('etymology-leak', why('pĭĕtas', 'pius', entry=self.PIETAS))

    def test_flags_the_etymon_after_a_conjugation_number(self):
        self.assertIn('etymology-leak', why('hūmāno', 'humanus', entry=self.HUMANO))

    def test_does_not_flag_the_real_gloss(self):
        self.assertNotIn('etymology-leak',
                         why('pĭĕtas', 'dutifulness, piety', entry=self.PIETAS))

    def test_does_not_flag_an_ordinary_one_word_gloss(self):
        self.assertNotIn('etymology-leak', why('stellŭla', 'star'))


class TestAdverbInheritsVerb(unittest.TestCase):
    def test_flags_an_adverb_given_its_verb_infinitive(self):
        self.assertIn('adv-inherits-verb',
                      why('acute', 'to sharpen, whet', source='xref-resolved'))

    def test_does_not_flag_an_adverbial_gloss(self):
        self.assertNotIn('adv-inherits-verb',
                         why('acute', 'sharply', source='xref-resolved'))


class TestNoObjection(unittest.TestCase):
    def test_a_good_gloss_has_no_reasons(self):
        self.assertEqual(why('stellŭla', 'little star'), [])

    def test_empty_gloss_returns_no_reasons(self):
        # empties are counted separately; reasons() deliberately says nothing
        self.assertEqual(why('x', ''), [])
        self.assertEqual(why('x', '   '), [])


if __name__ == '__main__':
    unittest.main()
