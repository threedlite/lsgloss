"""Integrity of the committed data files the package is rebuilt from.

README: these four files are committed precisely so the ZIP can be rebuilt with
no model. That makes them source, and source gets checked.
"""
import re, unittest
from tests.util import ROOT, needs_corpus, TSV, FREQ
from common import load_rows, load_entries
from tests.util import XML


@needs_corpus
class TestGlossTsv(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = load_rows(str(TSV))

    def test_row_count_matches_the_dictionary(self):
        # the TSV is positional: row i describes entry i. A mismatch silently
        # misaligns every downstream stage.
        self.assertEqual(len(self.rows), len(load_entries(str(XML))))

    def test_every_row_has_four_fields(self):
        bad = [r for r in self.rows if len(r) != 4]
        self.assertEqual(bad[:3], [])

    def test_no_gloss_contains_a_tab_or_newline(self):
        bad = [r[0] for r in self.rows if '\t' in r[2] or '\n' in r[2]]
        self.assertEqual(bad[:3], [])

    def test_keys_are_unique(self):
        keys = [r[0] for r in self.rows]
        dupes = [k for k in set(keys) if keys.count(k) > 1] if len(keys) != len(set(keys)) else []
        self.assertEqual(dupes[:3], [])

    def test_no_gloss_is_a_bare_xref_placeholder(self):
        # cross-references are resolved, never emitted as placeholders
        bad = [r[0] for r in self.rows if r[2].strip().upper() in ('XREF', 'NONE')]
        self.assertEqual(bad[:3], [])

    def test_source_column_is_from_the_known_set(self):
        known = {'model', 'repaired', 'tr', 'xref-resolved', 'xref-adapted', 'no-gloss', 'ls',
                 'hard', 'hard2', 'named', 'freqfix', 'override',
                 'xrefix', 'refilled'}
        bad = {r[3].rstrip('~?!') for r in self.rows} - known
        self.assertEqual(bad, set(), f'unknown source label: {bad}')


@needs_corpus
class TestFrequencyList(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lines = [l.split('\t') for l in
                     FREQ.read_text(encoding='utf-8').splitlines() if l]

    def test_counts_are_positive_integers(self):
        bad = [l for l in self.lines if not (len(l) == 2 and l[1].isdigit())]
        self.assertEqual(bad[:3], [])

    def test_is_sorted_by_descending_count(self):
        counts = [int(l[1]) for l in self.lines if len(l) == 2 and l[1].isdigit()]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_has_no_empty_word(self):
        # REVIEW.md finding 8: a blank key with count 9,480 ranked ~63rd.
        # FIXED in corpusfreq.py; passes once `make freq` has been re-run.
        blank = [i for i, l in enumerate(self.lines, 1) if not l[0].strip()]
        self.assertEqual(blank, [], f'empty word at line(s) {blank[:3]}')


if __name__ == '__main__':
    unittest.main()
