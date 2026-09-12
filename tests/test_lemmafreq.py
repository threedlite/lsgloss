"""Lemma frequency decides which entries the repair budget is spent on.

A wrong number here does not corrupt any gloss directly; it silently aims the
whole freqfix stage at the wrong words, which is the one thing that stage exists
to get right.
"""
import unittest
from tests.util import ROOT
from lemmafreq import load_form_counts, lemma_frequencies


class TestLoadFormCounts(unittest.TestCase):
    def test_folds_the_key(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / 'f.tsv'
            p.write_text('vel\t10\nuel\t5\n', encoding='utf-8')
            c = load_form_counts(str(p))
            # vel and uel are the same word; their counts must be summed
            self.assertEqual(c['uel'], 15)

    def test_ignores_non_numeric_rows(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / 'f.tsv'
            p.write_text('good\t3\nbad\tnotanumber\n', encoding='utf-8')
            c = load_form_counts(str(p))
            self.assertEqual(c.get('good'), 3)
            self.assertNotIn('bad', c)


class TestLemmaFrequencies(unittest.TestCase):
    ROWS = [['porta', 'porta', 'gate', 'model']]
    BODIES = ['porta, ae, f. a gate']

    def test_sums_over_the_generated_paradigm(self):
        # a reader meets porta as portam and portis, not only as the nominative
        lf = lemma_frequencies(self.ROWS, self.BODIES,
                               {'porta': 10, 'portam': 20, 'portis': 5})
        self.assertEqual(lf['porta'], 35)

    def test_a_lemma_with_no_corpus_hits_is_absent(self):
        lf = lemma_frequencies(self.ROWS, self.BODIES, {'nothing': 9})
        self.assertNotIn('porta', lf)

    def test_is_keyed_per_entry_not_per_stem(self):
        # `in1` and `in3` are different words; keying on the shared stem `in` and
        # taking the max gave the rare one the common one's whole count
        lf = lemma_frequencies([['porta2', 'porta', 'gate', 'model']],
                               self.BODIES, {'porta': 7})
        self.assertIn('porta2', lf)
        self.assertNotIn('porta', lf)


if __name__ == '__main__':
    unittest.main()
