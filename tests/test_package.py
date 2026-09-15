"""Invariants of the importable package.

These do not rebuild the ZIP -- regress.py already pins the inputs. They check
the properties an importing app relies on, which no stage asserts today: a
morphology row pointing at a lemma that is not in the dictionary is a dead link,
and a confidence outside 0..1 silently breaks candidate ranking.
"""
import csv, io, unittest, zipfile
from pathlib import Path

from tests.util import ROOT, needs_corpus, ZIP

have_zip = unittest.skipUnless(ZIP.exists(), 'out/lewis-short-glosses.zip not built')


def _read(name):
    with zipfile.ZipFile(ZIP) as z:
        with z.open(name) as fh:
            return list(csv.DictReader(io.TextIOWrapper(fh, encoding='utf-8')))


@have_zip
class TestPackageInvariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dictionary = _read('dictionary.csv')
        cls.morphology = _read('morphology.csv')
        cls.lemmas = {r['lemma'] for r in cls.dictionary}

    def test_dictionary_lemmas_are_unique(self):
        seen = [r['lemma'] for r in self.dictionary]
        self.assertEqual(len(seen), len(set(seen)), 'duplicate lemma in dictionary.csv')

    def test_every_dictionary_entry_has_a_definition(self):
        blank = [r['lemma'] for r in self.dictionary if not r['definition'].strip()]
        self.assertEqual(blank, [], f'{len(blank)} lemmas ship with no definition')

    def test_every_morphology_row_points_at_a_real_lemma(self):
        dead = {r['lemma'] for r in self.morphology if r['lemma'] not in self.lemmas}
        self.assertEqual(dead, set(), f'{len(dead)} dead lemma links in morphology.csv')

    def test_confidence_is_a_probability(self):
        bad = [r for r in self.morphology if not 0.0 <= float(r['confidence']) <= 1.0]
        self.assertEqual(bad, [], 'confidence outside 0..1 breaks candidate ranking')

    def test_word_forms_are_folded(self):
        from common import fold
        bad = [r['word_form'] for r in self.morphology[:200000]
               if fold(r['word_form']) != r['word_form']]
        self.assertEqual(bad[:5], [], 'unfolded word_form can never match a text')

    def test_no_duplicate_form_lemma_pair(self):
        seen = set(); dupes = []
        for r in self.morphology:
            k = (r['word_form'], r['lemma'])
            if k in seen:
                dupes.append(k)
            seen.add(k)
        self.assertEqual(dupes[:5], [], f'{len(dupes)} duplicate (form, lemma) rows')

    def test_morph_info_is_morphology_not_provenance(self):
        """The column the reader is shown must describe the WORD.

        It shipped 1.5M rows reading `generated paradigm`, `treebank`,
        `headword` -- which stage of package.py made the row. That is what
        `source_name` is for; provenance now goes to stderr at build time.
        """
        provenance = {'headword', 'treebank', 'model lemma', 'generated paradigm',
                      'paradigm + -que', 'paradigm + -ve', 'host + -que', 'host + -ve',
                      'enclitic'}
        leaked = sorted({r['morph_info'] for r in self.morphology} & provenance)
        self.assertEqual(leaked, [], f'provenance in morph_info: {leaked}')

    def test_almost_every_row_carries_a_parse(self):
        # Empty is legal in the format and honest where nothing knows the
        # answer: L&S names no part of speech in ~5,500 entries, most of them
        # cross-reference stubs ("Naevianus, v. 2. Naevius, B.") whose own text
        # says nothing about the word, and those entries' headwords carry their
        # -que and -ve rows with them. Currently 1.19%. It must stay the rare
        # exception -- and it must not be papered over with a filler like the
        # "lemma form" this column briefly carried, which is not morphology and
        # hid the gap rather than reporting it.
        blank = sum(1 for r in self.morphology if not r['morph_info'].strip())
        self.assertLess(blank / len(self.morphology), 0.02,
                        f'{blank:,} rows ship with no morph_info')

    def test_a_known_form_reads_the_way_the_format_documents(self):
        # DICTIONARY_IMPORT_FORMAT.md's own example row is
        # `est,sum,latin,3 s pres active ind,1.0,Lewis & Short`
        est = [r for r in self.morphology if r['word_form'] == 'est' and r['lemma'] == 'sum']
        self.assertTrue(est, 'est/sum missing')
        self.assertEqual(est[0]['morph_info'], '3 s pres active ind')

    def test_every_value_conforms_to_the_slot_schema(self):
        """The whole point: one schema, every row, whatever produced it.

        Parsing each value back into slots by position catches both an unknown
        word and a right word in the wrong place -- "dat/abl p" reads case
        before number and fails here, which is exactly how the first version of
        this column shipped alongside the treebank's "noun s m gen".
        """
        from inflect import SLOT_ORDER, SLOT_VALUES
        bad = []
        for value in {r['morph_info'] for r in self.morphology}:
            for reading in value.split('|'):
                pos = 0
                for token in reading.split():
                    while pos < len(SLOT_ORDER):
                        slot = SLOT_ORDER[pos]; pos += 1
                        if token in SLOT_VALUES[slot]: break
                    else:
                        bad.append(value); break
        self.assertEqual(sorted(bad)[:5], [], f'{len(bad)} values off-schema')

    def test_readings_within_a_cell_are_sorted_and_unique(self):
        # the cell is rebuilt from a set and sorted, so a rebuild is identical
        # and the alternatives read the way the existing 1.96M rows do
        bad = []
        for value in {r['morph_info'] for r in self.morphology if '|' in r['morph_info']}:
            parts = value.split('|')
            if parts != sorted(set(parts)): bad.append(value)
        self.assertEqual(sorted(bad)[:5], [], f'{len(bad)} cells unsorted or repeated')

    def test_no_part_of_speech_token_where_the_form_inflects(self):
        """Whitaker describes a noun by its case, never as "noun".

        Our rows land in the same `lemma_map` table as its 1.96M Latin rows and
        a reader gets both under one word, so a category token may appear only
        where Whitaker has no row at all: the indeclinables it does not index.
        """
        from inflect import SLOT_VALUES
        bad = []
        for r in self.morphology:
            # per READING, not per cell: a form can genuinely be an adverb or a
            # nominative singular (`adversus` is both, and ships as "adv|nom s"),
            # and those are alternatives rather than one confused reading
            for reading in r['morph_info'].split('|'):
                toks = [t for t in reading.split() if t not in SLOT_VALUES['clitic']]
                cats = [t for t in toks if t in SLOT_VALUES['category']]
                others = [t for t in toks if t not in SLOT_VALUES['category']]
                # `pron` is Whitaker's own and rides along with case and number
                if cats and others and cats != ['pron']:
                    bad.append((r['word_form'], r['morph_info']))
        self.assertEqual(bad[:5], [], f'{len(bad)} readings mix a category with inflection')

    def test_no_value_needs_csv_quoting(self):
        # a slot-shaped value has no commas in it; one that does is a sign
        # something free-form crept back in
        bad = sorted({r['morph_info'] for r in self.morphology if ',' in r['morph_info']})
        self.assertEqual(bad[:5], [], f'{len(bad)} values contain commas')

    def test_an_enclitic_form_resolves_to_both_its_words(self):
        """`virumque` is two words: *vir* and *-que*, "and".

        It used to resolve only to the host, so a reader met the token and was
        never told there was an "and" in it. 66% of this file is enclitic forms
        and nine rows in it named the enclitic.
        """
        rows = [r for r in self.morphology if r['word_form'] == 'uirumque']
        self.assertIn('vir', {r['lemma'] for r in rows})
        que = [r for r in rows if r['lemma'] == 'que']
        self.assertTrue(que, 'uirumque does not resolve to que')
        # and the row says it IS the enclitic, so a consumer can tell it from
        # the host row without guessing from the lemma's spelling
        from inflect import ENCLITIC_MORPH
        self.assertEqual(que[0]['morph_info'], ENCLITIC_MORPH)
        # the host leads, so ordinary lookup still finds the inflected word
        best = max(rows, key=lambda r: float(r['confidence']))
        self.assertNotIn(best['lemma'], ('que', 've'))

    def test_every_enclitic_row_is_marked_as_one(self):
        """A row whose lemma is the particle carries the `enclitic` marker, and
        no host row does. This is what the downstream reader asked for."""
        from inflect import ENCLITIC_MORPH
        bad = [r for r in self.morphology[:400000]
               if (r['lemma'] in ('que', 've')) != (r['morph_info'] == ENCLITIC_MORPH)]
        self.assertEqual(bad[:5], [], f'{len(bad)} rows mismarked')

    def test_a_treebank_host_gets_its_enclitic_form(self):
        # `eiusque` -- the host `eius` comes from the treebank, not a paradigm
        # (`idque` is too short for split_enclitic's stem guard, by design)
        rows = [r for r in self.morphology if r['word_form'] == 'eiusque']
        self.assertIn('is', {r['lemma'] for r in rows}, 'eiusque not joined to its host')

    def test_a_bare_etymon_does_not_ship(self):
        # pietas -> "pius": flagged etymology-leak in the TSV, and the package
        # leaves it to Whitaker rather than show a reader a Latin word
        bad = [r['lemma'] for r in self.dictionary if r['definition'].strip().lower() == r['lemma']]
        self.assertEqual(bad[:5], [], f'{len(bad)} lemmas glossed as themselves')
        self.assertNotIn('pius', {r['definition'] for r in self.dictionary if r['lemma'] == 'pietas'})

    def test_no_flagged_or_editorial_gloss_ships(self):
        # "false reading in Vitruvius" is apparatus; the bare "of or belonging"
        # is a gloss cut off before its complement. Both shipped on 2026-09-11.
        import re
        bad = [r['lemma'] for r in self.dictionary
               if r['definition'].lower().startswith('false reading')
               or re.match(r'^of or \\w+$', r['definition'].lower())]
        self.assertEqual(bad[:5], [], f'{len(bad)} apparatus or truncated glosses shipped')

    def test_a_minor_homograph_keeps_its_own_forms(self):
        """L&S has sĭon, ii, n. (water-parsley) and Sīon, ōnis (Jerusalem). The
        neuter's own forms (*sio*, *sii*) were filed under the primary `sion`
        and a reader of Pliny was told water-parsley is a hill of Jerusalem."""
        if 'sion2' not in self.lemmas:
            self.skipTest('sion2 absent')
        sio = {r['lemma'] for r in self.morphology if r['word_form'] == 'sio'}
        self.assertIn('sion2', sio); self.assertNotIn('sion', sio)
        # a form both paradigms make still leads to the primary sense
        self.assertIn('sion', {r['lemma'] for r in self.morphology if r['word_form'] == 'sion'})

    def test_an_author_citation_is_not_resolved_as_a_reference(self):
        # `illatenus` ("so far") read "cf. Fronto Ter. Als. 4." as a pointer to
        # the entry `fronto` and shipped as "broad-forehead person"
        for lem in ('illatenus', 'illactenus'):
            for r in self.dictionary:
                if r['lemma'] == lem:
                    self.assertNotIn('forehead', r['definition'])

    def test_a_name_homograph_follows_the_annotators(self):
        """Where a name and a common word share a lemma, the treebank count
        decides the primary sense when it is decisive; article length otherwise.
        The rule is confined to name homographs: `cum` stays the conjunction
        although the annotators' lemma count favours the preposition."""
        d = {r['lemma']: r['definition'] for r in self.dictionary}
        if 'crassus' in d:
            self.assertIn('gens Licinia', d['crassus'])         # Cicero's Crassus, 11 tokens to 0
        if 'pontus' in d:
            self.assertIn('sea', d['pontus'])                   # the common noun, 11 to 0
        if 'cum' in d:
            self.assertTrue(d['cum'].startswith('when'))
        if 'magnus' in d:
            self.assertIn('great', d['magnus'])
        if 'castor' in d:
            self.assertIn('Tyndarus', d['castor'])              # not decisive: the article rule

    def test_the_annotators_majority_leads_a_form(self):
        """`se` led with the prefix ("sine, without"), `hoc` with the adverb,
        `ac` with "sharp": a headword row at 1.0 outranked the treebank's row
        for the real word. The annotators' two-thirds majority now leads."""
        lead = {}
        for r in self.morphology:
            w = r['word_form']
            if w in ('se', 'hoc', 'ac', 'te', 'quid', 'alia', 'populi', 'suo', 'suae', 'me'):
                c = float(r['confidence'])
                if w not in lead or c > lead[w][0]: lead[w] = (c, r['lemma'])
        for form, want in (('se', 'sui'), ('hoc', 'hic'), ('ac', 'atque'), ('te', 'tu'), ('quid', 'quis'),
                           ('alia', 'alius'), ('populi', 'populus')):
            if form in lead:
                self.assertEqual(lead[form][1], want, f'{form} leads with {lead[form][1]}')
        # a form whose majority lemma is not in the dictionary (*suus*, left to
        # the app's own data) ships no row rather than "to stitch" / "a town in Assyria"
        self.assertNotIn('suo', lead); self.assertNotIn('suae', lead)
        # ...unless the entry is itself a pointer to that lemma: `me`, "v. ego"
        self.assertIn('me', lead)

    def test_function_words_lead_their_homographs_or_go_to_the_app(self):
        """`nec` led with the prefix ("inseparable negative particle"), `vero`
        with the verb "to speak the truth", `magis` with the dish. The function
        word leads; where its gloss is an adjective's inherited through a
        cross-reference, the lemma goes to the app's own data instead."""
        d = {r['lemma']: r['definition'] for r in self.dictionary}
        if 'nec' in d:
            self.assertTrue(d['nec'].startswith('not'), d['nec'])
        for lem in ('magis', 'celeriter', 'ab', 'animus'):
            self.assertNotIn(lem, d, f'{lem} ships a frame or an inherited adjective: {d.get(lem)!r}')
        # `a` the preposition: *ab* is rejected, its copy under `a` with it, and
        # the form leads nowhere rather than to the letter or the interjection
        self.assertEqual([r['lemma'] for r in self.morphology if r['word_form'] == 'a'], [])
        for lem, word in (('sum', 'be'), ('sero', 'sow')):
            if lem in d:
                self.assertIn(word, d[lem], f'{lem}: {d[lem]!r}')
        if 'eo' in d:                                     # the adverb leads, not the verb "to go"
            self.assertNotIn('go', d['eo'].split(', ')[0].split())
        if 'os' in d:                                     # os1 the mouth leads, not os2 the bone
            self.assertNotIn('bone', d['os'])
        if 'vero' in d:                                   # the adverb's row is excluded; the verb leads
            self.assertNotIn('true', d['vero'])
        if 'tamen' in d:
            self.assertTrue(d['tamen'].startswith('nevertheless'), d['tamen'])

    def test_no_nationality_the_entry_never_states(self):
        # Timarchides is "a sculptor" in L&S; the model made him Athenian
        d = {r['lemma']: r['definition'] for r in self.dictionary}
        if 'timarchides' in d:
            self.assertEqual(d['timarchides'], 'sculptor')

    def test_no_enclitic_row_without_its_host(self):
        """If the half in front of -que is not indexed, the joined form is not a
        word we can offer: the reader could not look its first half up."""
        from inflect import split_enclitic
        index = {}
        for r in self.morphology:
            index.setdefault(r['word_form'], set()).add(r['lemma'])
        lemmas = {r['lemma'] for r in self.dictionary}
        orphan = []
        for form, lems in index.items():
            stem, enc = split_enclitic(form)
            if not enc or form in lemmas:
                continue          # a word in its own right is kept as it is
            if not (lems - {'que', 've'}):
                orphan.append(form)
        self.assertEqual(sorted(orphan)[:5], [],
                         f'{len(orphan)} joined forms have no host candidate')

    def test_a_word_that_merely_ends_in_que_is_not_split(self):
        """`usque`, `namque`, `itaque`, `quoque` and `denique` are words, not a
        host plus an enclitic, and each has its own L&S entry."""
        lemmas = {r['lemma'] for r in self.dictionary}
        for w in ('usque', 'denique', 'undique', 'absque', 'quoque'):
            if w not in lemmas: continue
            rows = [r for r in self.morphology if r['word_form'] == w]
            best = max(rows, key=lambda r: float(r['confidence']))
            self.assertEqual(best['lemma'], w,
                             f'{w} does not lead with its own entry')

    def test_ambiguous_forms_are_capped_at_three_candidates(self):
        from collections import Counter
        c = Counter(r['word_form'] for r in self.morphology)
        over = [w for w, n in c.items() if n > 3]
        self.assertEqual(over[:5], [], f'{len(over)} forms exceed the 3-candidate cap')


@have_zip
class TestKnownAmbiguity(unittest.TestCase):
    """The README's worked example: `oris` must keep every candidate, best first."""

    @classmethod
    def setUpClass(cls):
        cls.morphology = _read('morphology.csv')

    def test_oris_keeps_more_than_one_candidate(self):
        rows = [r for r in self.morphology if r['word_form'] == 'oris']
        self.assertGreater(len(rows), 1,
                           'a genuine ambiguity was collapsed to one answer')

    def test_frequent_lemma_wins_a_collision(self):
        # `cum` must resolve to cum, not to Spaco whose paradigm also makes it
        rows = [r for r in self.morphology if r['word_form'] == 'cum']
        if not rows:
            self.skipTest('cum absent')
        best = max(rows, key=lambda r: float(r['confidence']))
        self.assertEqual(best['lemma'], 'cum')


if __name__ == '__main__':
    unittest.main()
