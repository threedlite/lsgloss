"""The three normalisers are the join keys of the whole package.

README: confusing them "is the easiest way to break this project quietly".
`fold` keys word_form, `plain` keys lemma, `letters` compares English prose.
A drift between them unlinks morphology.csv from dictionary.csv, which is a
silent, total failure -- every lookup misses and nothing raises.
"""
import unittest
from tests.util import ROOT
from common import fold, plain, letters, txt, focus


class TestFold(unittest.TestCase):
    """word_form key: accents dropped, i/j and u/v merged."""

    def test_merges_i_j_and_u_v(self):
        # editions differ in which glyph they print for the same word
        self.assertEqual(fold('juvo'), fold('iuuo'))
        self.assertEqual(fold('virum'), fold('uirum'))
        self.assertEqual(fold('jam'), fold('iam'))

    def test_drops_macrons_and_breves(self):
        self.assertEqual(fold('ăb'), 'ab')
        self.assertEqual(fold('Spāco'), 'spaco')
        self.assertEqual(fold('oppugnātor'), 'oppugnator')

    def test_spells_out_ligatures(self):
        # NFKD does not decompose ae/oe; without the explicit table the
        # non-letter strip deletes them and `quæso` folds to `quso`
        self.assertEqual(fold('quæso'), 'quaeso')
        self.assertEqual(fold('cœlum'), 'coelum')

    def test_dianoea_is_not_diana(self):
        # the bug the README calls out: `diānœa` folded to `diana` and outranked
        # the goddess for that form
        self.assertEqual(fold('diānœa'), 'dianoea')
        self.assertNotEqual(fold('diānœa'), fold('Diana'))


class TestPlain(unittest.TestCase):
    """lemma key: accents dropped, spelling otherwise preserved."""

    def test_does_not_fold_i_j_or_u_v(self):
        # a lemma must stay the headword a reader looks up
        self.assertEqual(plain('juvo'), 'juvo')
        self.assertEqual(plain('virum'), 'virum')
        self.assertNotEqual(plain('juvo'), plain('iuuo'))

    def test_drops_accents(self):
        self.assertEqual(plain('tŭnĭca'), 'tunica')

    def test_keeps_hyphen(self):
        # L&S prints compounds hyphenated: "ab-brevio"
        self.assertEqual(plain('ab-utor'), 'ab-utor')


class TestLetters(unittest.TestCase):
    """prose key: an English gloss must not have its v's turned into u's."""

    def test_leaves_v_and_j_alone(self):
        self.assertEqual(letters('victory'), 'victory')
        self.assertEqual(letters('juvo'), 'juvo')

    def test_strips_punctuation_and_case(self):
        self.assertEqual(letters('Raven-black, color!'), 'ravenblackcolor')


class TestNormalisersAreDistinct(unittest.TestCase):
    def test_the_three_differ_where_it_matters(self):
        # if any two of these ever coincide on this word, the distinction the
        # README describes has been lost
        self.assertEqual((fold('juvo'), plain('juvo'), letters('juvo')),
                         ('iuuo', 'juvo', 'juvo'))


class TestTxt(unittest.TestCase):
    def test_strips_tags_and_collapses_whitespace(self):
        self.assertEqual(txt('<orth>a<hi>b</hi></orth>\n  c'), 'ab c')

    def test_empty(self):
        self.assertEqual(txt('   \n '), '')


class TestFocus(unittest.TestCase):
    """Put the definition first by removing the apparatus L&S opens with."""

    def test_strips_parentheses_and_brackets_from_the_body(self):
        # focus() is head + ': ' + stripped-body. Only the body is stripped; the
        # head is the raw text up to the first comma, apparatus and all.
        self.assertEqual(focus('word (variant) [etym] meaning'),
                         'word (variant) [etym] meaning: word meaning')

    def test_strips_nested_parentheses_from_the_body(self):
        body = focus('w (a (b) c) def').split(': ', 1)[1]
        self.assertEqual(body, 'w def')

    def test_definition_leads_once_the_apparatus_is_gone(self):
        # the point of the function: a truncated long entry must still contain
        # its definition rather than pages of Indo-European cognates
        got = focus('ab, prep. (a, af, abs) [cf. Sanscr. api] from, away from')
        self.assertIn('from, away from', got[:80])

    def test_prefixes_the_headword(self):
        self.assertTrue(focus('porta, ae, f. a gate').startswith('porta:'))


if __name__ == '__main__':
    unittest.main()
