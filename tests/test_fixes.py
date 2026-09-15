"""Executable specs for the 2026-09-12 review fixes.

Each test names the defect it pins. They are the guard against any of these
coming back; the corpus-wide diff in regress.py is the guard against their
fixes touching anything else.
"""
import json, subprocess, sys, tempfile, unittest
from pathlib import Path

from tests.util import ROOT
from tests.fakemodel import FakeModel
from clean_gloss import clean, enforce, strip_unstated_nationality
from namegloss import name_gloss, name_clean, is_name_entry, NAME_MAXWORDS
from suspect import reasons, function_entry, strip_head_echo
from inflect import forms_with_morph, _noun_stem_and_key, render_morph, parse_reading, SLOT_ORDER
from common import (parse_score, xref_target_word, XrefIndex, checkpointed, load_ckpt,
                    pos_marker, focus)

FIX = Path(__file__).resolve().parent / 'fixtures'


class TestCleanTrailingPeriod(unittest.TestCase):
    """ABBR read any short word with a trailing period as a citation."""

    def test_a_lowercase_final_word_with_a_period_is_kept(self):
        self.assertEqual(clean('wild wolf.'), 'wild wolf')
        self.assertEqual(clean('wolf.'), 'wolf')
        self.assertEqual(clean('to sew on.'), 'to sew on')

    def test_an_author_abbreviation_is_still_cut(self):
        self.assertEqual(clean('eagle, Plin.'), 'eagle')
        self.assertEqual(clean('accent, Gell. 13, 6'), 'accent')

    def test_a_lowercase_citation_abbreviation_is_still_cut(self):
        self.assertEqual(clean('shield, id.'), 'shield')
        self.assertEqual(clean('law t. t. lawsuit'), 'law')

    def test_a_count_followed_by_a_word_is_prose(self):
        self.assertEqual(clean('one of 12 lictors'), 'one of 12 lictors')
        self.assertEqual(clean('raven-black color, Vitr. 8, 3'), 'raven-black color')


class TestEnforceKeepsTheComplement(unittest.TestCase):
    """'of or belonging to a deity' shipped as 'of or belonging' on 555 rows."""

    CASES = {'of or belonging to a deity': 'belonging to a deity',
             'of or pertaining to the sea': 'pertaining to the sea',
             'of or belonging to a wild boar': 'belonging to a wild boar'}

    def test_drops_of_or_before_the_participle(self):
        for src, want in self.CASES.items():
            with self.subTest(src):
                self.assertEqual(enforce(src, 5), want)

    def test_never_ends_on_a_bare_participle(self):
        for g in ('of or belonging to Mentesa in Hispania Baetica',
                  'of or relating to interest or usury and money'):
            with self.subTest(g):
                self.assertNotIn(enforce(g, 5).split()[-1], ('belonging', 'pertaining', 'relating', 'to'))

    def test_is_idempotent_and_capped(self):
        for src in self.CASES:
            e = enforce(src, 5)
            self.assertEqual(enforce(e, 5), e)
            self.assertLessEqual(len(e.split()), 5)

    def test_the_fragment_detector_now_sees_the_bare_participle(self):
        self.assertIn('fragment', reasons('divinus', 'of or belonging', 'model~',
                                          'divinus, a, um, adj. of or belonging to a deity'))
        # ...even on an entry the function-word exemption covers
        self.assertIn('fragment', reasons('trecenarius', 'of or belonging', 'model',
                                          'trecenarius, a, um, adj. num. of or belonging to three hundred'))
        self.assertNotIn('fragment', reasons('ex', 'out of, from', 'model',
                                             'ex, praep. with abl. out of, from'))


class TestYBreveFolding(unittest.TestCase):
    """Perseus writes y-breve as Cyrillic U+045E; it folded to nothing."""

    def test_y_breve_is_a_y(self):
        from common import fold, letters, plain
        self.assertEqual(fold('Cărўae'), 'caryae')
        self.assertEqual(letters('Bacchўlĭdēs'), 'bacchylides')
        self.assertEqual(plain('Cărўae'), 'caryae')

    def test_a_headword_echoed_through_a_y_breve_is_caught(self):
        self.assertIn('bare-echo', reasons('Bacchўlĭdēs', 'Bacchylides', 'repaired',
                                           'Bacchylides, is, m., a Greek lyric poet'))


class TestNameGlossRendering(unittest.TestCase):
    """'Roman nomen' is half Latin; six phrasings of one category read as six."""

    def test_one_english_rendering_per_category(self):
        self.assertEqual(clean('Roman nomen'), 'Roman family name')
        self.assertEqual(clean('Roman gens name'), 'Roman family name')
        self.assertEqual(clean('name of a Roman gens'), 'Roman family name')
        self.assertEqual(clean('Roman cognomen in gens Fabia'), 'Roman surname in gens Fabia')

    def test_a_surname_stays_a_surname(self):
        self.assertEqual(clean('Roman surname'), 'Roman surname')


class TestEditorialApparatus(unittest.TestCase):
    ENTRY = 'abathon, a false reading in Vitr. 5, 6'

    def test_flags_false_reading(self):
        self.assertIn('editorial-apparatus', reasons('abathon', 'false reading in Vitruvius', 'hard', self.ENTRY))
        self.assertIn('editorial-apparatus', reasons('luteae', 'false reading for uvam', 'repaired', self.ENTRY))

    def test_does_not_flag_prose_about_reading(self):
        self.assertNotIn('editorial-apparatus', reasons('lectio', 'reading, perusal', 'model',
                                                        'lectio, onis, f. a reading'))


class TestFunctionEntryWindow(unittest.TestCase):
    """'Tert. adv. Marc.' exempted 1,616 noun and adjective entries."""

    def test_a_cited_adversus_is_not_a_marker(self):
        f = focus('acatus, i, f., a light vessel or boat, Tert. adv. Marc. 5, 1 med.')
        self.assertFalse(function_entry(f))

    def test_the_headword_marker_still_counts(self):
        self.assertTrue(function_entry(focus('ab, praep. with abl. from, away from')))
        self.assertTrue(function_entry(focus('abhinc, temp. adv. of past time, ago')))

    def test_a_derived_adverb_note_is_not_a_marker(self):
        f = focus('actualis, e, adj. id., active, practical, Macr. Somn. Scip. 2, 17.—Adv.: actualiter')
        self.assertFalse(function_entry(f))


class TestJudgeScoreParsing(unittest.TestCase):
    def test_reads_the_leading_digit(self):
        self.assertEqual(parse_score('4 accurate but thin'), 4)
        self.assertEqual(parse_score('(3) secondary sense'), 3)

    def test_does_not_take_a_number_from_prose(self):
        # '\\b([0-5])\\b' scored this 3
        self.assertIsNone(parse_score('The gloss has 3 words and I would rate it 4'))

    def test_unparseable_is_none_not_a_score(self):
        self.assertIsNone(parse_score(''))
        self.assertIsNone(parse_score('cannot judge'))


class TestCrossReferenceTarget(unittest.TestCase):
    def test_v_inside_adv_is_not_a_reference(self):
        # resolved to the entry `comp` before
        self.assertIsNone(xref_target_word('Adv. comp., abditius'))

    def test_verb_marker_is_not_a_reference(self):
        # "v. a." resolved to the entry a2, "first letter of the Latin alphabet"
        self.assertEqual(xref_target_word('x, v. a., v. abicio')[1], 'abicio')
        self.assertIsNone(xref_target_word('abbrevio, are, v. freq. a., to shorten'))

    def test_one_letter_target_is_not_a_reference(self):
        # "v. h. v." is vide hoc verbum
        self.assertIsNone(xref_target_word('patalis, false reading of patulus, v. h. v.'))

    def test_homograph_number_is_honoured(self):
        rows = [['repens1', 'repens', 'creeping', 'model'], ['repens2', 'repens', 'sudden', 'model'],
                ['x', 'x', '', 'xref']]
        bodies = ['repens, creeping', 'repens, sudden', 'x, v. 2. repens']
        self.assertEqual(XrefIndex(rows, bodies).target_of(2), 1)


class TestPosMarker(unittest.TestCase):
    def test_reads_the_headword_line(self):
        self.assertEqual(pos_marker('vero, adv., v. verus'), 'adv')
        self.assertEqual(pos_marker('pater, tris, m. father'), None)


class TestCheckpointRetriesFailures(unittest.TestCase):
    """A failed call was written as 'ERROR: ...' and skipped forever on resume."""

    def test_a_failure_is_not_written_and_a_success_is(self):
        with tempfile.TemporaryDirectory() as d:
            ck = Path(d) / 'c.jsonl'
            work = lambda i: None if i == 2 else {'i': i, 'g': f'g{i}'}
            got = checkpointed(str(ck), [1, 2, 3], work, jobs=2, tag='t', extra={'p': 'main'},
                               log=lambda s: None)
            self.assertEqual(sorted(r['i'] for r in got), [1, 3])
            done = load_ckpt(str(ck), 'main')
            self.assertEqual(sorted(done), [1, 3])
            self.assertEqual(done[1]['g'], 'g1')


class TestParadigmStems(unittest.TestCase):
    """Abbreviated genitives were glued on wrongly: filiusi, hoinem, pattrem."""

    def test_second_declension_ii(self):
        self.assertEqual(_noun_stem_and_key('filius', 'ii'), ('fili', 'i'))
        f = forms_with_morph('filius', 'filius, ii, m. a son')
        self.assertIn('filii', f); self.assertIn('filio', f); self.assertNotIn('filiusi', f)

    def test_third_declension_abbreviations(self):
        self.assertEqual(_noun_stem_and_key('homo', 'inis'), ('homin', 'is'))
        self.assertEqual(_noun_stem_and_key('pater', 'tris'), ('patr', 'is'))
        self.assertEqual(_noun_stem_and_key('corpus', 'oris'), ('corpor', 'is'))
        self.assertEqual(_noun_stem_and_key('liber', 'bri'), ('libr', 'i'))
        self.assertEqual(_noun_stem_and_key('ager', 'gri'), ('agr', 'i'))

    def test_compound_guard_still_holds(self):
        f = forms_with_morph('vigintivir', 'vigintivir, viri, m. one of a board of twenty')
        self.assertNotIn('uirum', f); self.assertIn('uigintiuiri', f)

    def test_third_declension_dative_singular(self):
        self.assertEqual(forms_with_morph('rex', 'rex, regis, m. a king')['regi'], 'dat s m')
        self.assertIn('homini', forms_with_morph('homo', 'homo, inis, m. a man'))

    def test_i_stem_genitive_plural_only_for_i_stems(self):
        self.assertNotIn('regium', forms_with_morph('rex', 'rex, regis, m. a king'))
        self.assertIn('urbium', forms_with_morph('urbs', 'urbis, f. a city'.join(['urbs, ', ''])))
        self.assertIn('ciuium', forms_with_morph('civis', 'civis, is, m. a citizen'))

    def test_bare_is_genitive_declines(self):
        m = forms_with_morph('mare', 'mare, is, n. the sea')
        self.assertEqual(m['maria'], 'acc p n|nom p n|voc p n')
        self.assertIn('mari', m)

    def test_nominative_endings_only_where_the_headword_has_them(self):
        self.assertNotIn('agrer', forms_with_morph('ager', 'ager, gri, m. a field'))
        self.assertNotIn('populer', forms_with_morph('populus', 'populus, i, m. a people'))
        self.assertNotIn('puere', forms_with_morph('puer', 'puer, eri, m. a boy'))
        self.assertIn('serue', forms_with_morph('servus', 'servus, i, m. a slave'))

    def test_deus_is_not_fifth_declension(self):
        f = forms_with_morph('deus', 'deus, dei, m. a god')
        self.assertIn('deo', f); self.assertNotIn('derum', f)

    def test_deponent_present_stem_and_endings(self):
        m = forms_with_morph('vereor', 'vereor, itus, 2, v. dep. a. to fear')
        self.assertNotIn('uereoreo', m)
        self.assertEqual(m['ueretur'], '3 s pres ind')
        self.assertNotIn('ueret', m)
        m = forms_with_morph('moror', 'moror, atus, 1, v. dep. n. to delay')
        self.assertNotIn('morat', m); self.assertIn('moratur', m)


class TestEncliticSlot(unittest.TestCase):
    def test_renders_and_parses(self):
        self.assertEqual(render_morph({'category': 'conj', 'clitic': 'enclitic'}), 'conj enclitic')
        self.assertEqual(parse_reading('conj enclitic'), {'category': 'conj', 'clitic': 'enclitic'})
        self.assertEqual(SLOT_ORDER[-1], 'clitic')


class TestOfflineRebuild(unittest.TestCase):
    """lsgloss.py --offline rebuilds the TSV from the checkpoint with no model."""

    def _run(self, ckpt_lines, extra=()):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 'c.jsonl').write_text('\n'.join(json.dumps(x) for x in ckpt_lines) + '\n', encoding='utf-8')
            proc = subprocess.run([sys.executable, str(ROOT / 'lsgloss.py'), '--xml', str(FIX / 'mini_xref.xml'),
                                   '--out', str(d / 'o.tsv'), '--ckpt', str(d / 'c.jsonl'),
                                   '--url', 'http://127.0.0.1:9/', '--offline'] + list(extra),
                                  capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            rows = {}
            for line in (d / 'o.tsv').read_text(encoding='utf-8').splitlines():
                if not line.startswith('#'):
                    f = line.split('\t'); rows[f[0]] = f
            return rows, proc.stderr

    def test_makes_no_model_call_and_uses_the_checkpoint(self):
        rows, err = self._run([{'i': 0, 'g': 'true, real, genuine', 'p': 'main'},
                               {'i': 3, 'g': 'star', 'p': 'main'}])
        self.assertEqual(rows['verus'][2], 'true, real, genuine')
        self.assertEqual(rows['stella'][2], 'star')
        self.assertEqual(rows['vero'][3], 'xref-resolved')          # follows verus
        self.assertEqual(rows['vero'][2], 'true, real, genuine')
        self.assertIn('offline', err)

    def test_an_unanswered_row_is_left_empty_not_invented(self):
        rows, _ = self._run([{'i': 0, 'g': 'true, real, genuine', 'p': 'main'}])
        self.assertEqual(rows['stella'][2], '')

    def test_carry_keeps_a_model_verified_repair(self):
        with tempfile.TemporaryDirectory() as d:
            prev = Path(d) / 'prev.tsv'
            prev.write_text('verus\tvērus\ttrue, real, genuine\tmodel\n'
                            'vero\tvērō\tin truth, certainly\txrefix\n', encoding='utf-8')
            rows, _ = self._run([{'i': 0, 'g': 'true, real, genuine', 'p': 'main'}],
                                ['--carry', str(prev)])
            self.assertEqual(rows['vero'][2], 'in truth, certainly')
            self.assertEqual(rows['vero'][3], 'xrefix')




# ---------------------------------------------------------------- 2026-09-13
# Fixes after the downstream reader's second pass (feedback/RESPONSE_2026-09-13.md).

class TestOfOrStripIsGeneral(unittest.TestCase):
    """Naming three participles left "of or made", "of or suited", "of or
    dwelling" shipping on seven rows: the cut is the same whatever follows."""

    CASES = {'of or made of fine linen': 'made of fine linen',
             'of or proceeding from a command': 'proceeding from a command',
             'of or dwelling in a village': 'dwelling in a village',
             # still over the cap without "of or": the cut then lands on a phrase
             'of or suited to an assembly of the people': 'suited to an assembly',
             'of or caused by a master or teacher': 'caused by a master',
             'of or amounting to a scruple (in weight)': 'amounting to a scruple',
             # the earlier cases are unchanged
             'of or belonging to a deity': 'belonging to a deity',
             'of or pertaining to the sea': 'pertaining to the sea'}

    def test_never_ships_of_or_and_one_word(self):
        for src, want in self.CASES.items():
            with self.subTest(src):
                e = enforce(src, 5)
                self.assertEqual(e, want)
                self.assertEqual(enforce(e, 5), e)

    def test_the_fragment_detector_sees_any_third_word(self):
        for g in ('of or made', 'of or suited', 'of or dwelling'):
            with self.subTest(g):
                self.assertIn('fragment', reasons('carbaseus', g, 'model~',
                                                  'carbaseus, a, um, adj. of or made of fine linen'))
        self.assertNotIn('fragment', reasons('carbaseus', 'made of fine linen', 'model~',
                                             'carbaseus, a, um, adj. of or made of fine linen'))


class TestBareFunctionWordGloss(unittest.TestCase):
    """`inenarrativus` shipped as "not" and `Iliberi` as "to"."""

    def test_one_function_word_on_an_ordinary_entry_is_a_fragment(self):
        self.assertIn('fragment', reasons('inenarrativus', 'not', 'hard',
                                          'in-enarrativus, a, um, adj. 2. inenarro, not adapted for relation'))
        self.assertIn('fragment', reasons('Iliberi', 'to', 'hard2', 'Iliberi, v. Illiberi.'))

    def test_a_function_word_entry_keeps_its_gloss(self):
        self.assertNotIn('fragment', reasons('haud', 'not', 'model', 'haud, adv. not, not at all'))
        self.assertNotIn('fragment', reasons('ex', 'out of, from', 'model', 'ex, praep. with abl. out of, from'))

    def test_a_cross_reference_may_inherit_one(self):
        self.assertNotIn('fragment', reasons('noenum', 'not', 'xref-resolved', 'noenum and noenu, v. non init.'))

    def test_a_pronoun_form_keeps_its_pronoun_gloss(self):
        # sos, ibus, im, ea: archaic forms of *is*, glossed "he, she, it"
        self.assertNotIn('fragment', reasons('sos', 'he, she, it', 'xref-resolved', 'sos, archaic for eos, v. is'))
        self.assertNotIn('fragment', reasons('sos', 'them', 'model', 'sos, archaic for eos'))
        # ...but a relative clause cut down to its pronoun is still a fragment
        self.assertIn('fragment', reasons('praesaltor', 'he who is', 'repaired~', 'praesaltor, oris, m. he who led the Salii'))


class TestAuthorCitationIsNotAReference(unittest.TestCase):
    """"cf. Fronto Ter. Als. 4." cites Fronto; `illatenus` resolved to the entry
    `fronto` and shipped as "broad-forehead person"."""

    ILLATENUS = ('illatenus or illactenus, adv. illetenus, so far (post-class. and very rare): '
                 'litteras illatenus, qua dixi, legendas praebebat, App. Mag. p. 326; cf. Fronto Ter. Als. 4.')

    def test_author_followed_by_a_work_is_a_citation(self):
        self.assertIsNone(xref_target_word(self.ILLATENUS))
        self.assertIsNone(xref_target_word('x, v. Charis. p. 165 P.'))
        self.assertIsNone(xref_target_word('y, cf. Plin. 34, 8'))

    def test_a_capitalised_entry_is_still_a_reference(self):
        self.assertEqual(xref_target_word('Iliberi, v. Illiberi.'), (None, 'Illiberi'))
        self.assertEqual(xref_target_word('Hispane, adv., after the manner of Spain, v. Hispani, II. A. fin.'),
                         (None, 'Hispani'))
        self.assertEqual(xref_target_word('versum (vors-), v. 2. versus.'), ('2', 'versus'))
        self.assertEqual(xref_target_word('decuriatim, adv. id.; cf. centuriatim, by decuriae, v. Charis. p. 165 P.'),
                         (None, 'centuriatim'))


class TestUnstatedNationality(unittest.TestCase):
    """The prompt says "never state a nationality the entry does not state";
    the model wrote "Athenian sculptor" over an entry reading "a sculptor"."""

    def test_drops_an_ethnic_adjective_the_entry_never_mentions(self):
        self.assertEqual(strip_unstated_nationality('Athenian sculptor', 'Timarchides, is, m., a sculptor, Plin. 34'),
                         'sculptor')
        self.assertEqual(strip_unstated_nationality('Athenian rhetorician',
                                                    'Gorgias, ae, m., a famous Greek sophist of Leontini'),
                         'rhetorician')
        self.assertEqual(strip_unstated_nationality('hail! (Persian)', 'chaere, = χαῖρε, hail!'), 'hail!')

    def test_keeps_one_the_entry_states_in_any_spelling(self):
        for g, e in (('Athenian courtesan', 'Thais, idis, f., a celebrated courtesan of Athens'),
                     ('Athenian courtesan', 'Procris, a daughter of the Athenian king Erechtheus'),
                     ('island in the Tyrrhenian Sea', 'Capreae, an island in the Tyrrhene Sea'),
                     ('Lacedemonian general', 'Cleombrotus, a Lacedaemonian general'),
                     ('Egyptian Vulcan', 'Phthas, Aegyptiorum Vulcanus'),
                     ('Spanish style', 'Hispane, after the manner of Spain'),
                     ('Trojan companion of Aeneas', 'Alcander, a Trojan, Verg.'),
                     ('Greek sophist', 'Gorgias, ae, m., = Γοργίας, a sophist of Leontini'),
                     ('Danubian island', 'Peuce, an island in the Danube')):
            with self.subTest(g):
                self.assertEqual(strip_unstated_nationality(g, e), g)

    def test_roman_is_the_dictionary_frame(self):
        self.assertEqual(strip_unstated_nationality('Roman surname', 'Cossus, i, m., a surname in the gens Cornelia'),
                         'Roman surname')

    def test_never_empties_a_gloss_and_tidies_the_dangle(self):
        self.assertEqual(strip_unstated_nationality('Athenian', 'Atticus, of Attica'), 'Athenian')
        # only the head phrase is touched: cutting a later adjective leaves
        # "island in the Sea"
        self.assertEqual(strip_unstated_nationality('tunny fish of the Mediterranean', 'colias, a kind of tunny'),
                         'tunny fish of the Mediterranean')
        self.assertEqual(strip_unstated_nationality('celebrated Greek general of the Achaean league',
                                                    'a celebrated general of the Achaeans'),
                         'celebrated general of the Achaean league')
        self.assertEqual(strip_unstated_nationality('sculptor', 'x'), 'sculptor')


class TestNameGloss(unittest.TestCase):
    """A proper name takes the entry's own italic definition, not the model's."""

    def test_takes_the_first_italic_of_the_first_sense(self):
        e = ('<entryFree key="Timarchides"><orth>Tīmarchĭdes</orth>, is, m., <sense n="I">'
             '<hi rend="ital">a sculptor</hi>, <bibl>Plin. 34, 8</bibl></sense></entryFree>')
        self.assertEqual(name_gloss(e, 'Tīmarchĭdes'), 'a sculptor')
        e = ('<entryFree key="Hercules"><orth>Hercŭles</orth>, is, m., <sense n="I">'
             '<hi rend="ital">son of Jupiter and Alcmena</hi>; <hi rend="ital">the poplar</hi></sense></entryFree>')
        self.assertEqual(name_gloss(e, 'Hercŭles'), 'son of Jupiter and Alcmena')

    def test_skips_a_headword_echo_and_a_grammar_note(self):
        e = ('<entryFree key="Abbassus"><sense n="I"><hi rend="ital">Abbassus</hi>, '
             '<hi rend="ital">a town in Phrygia</hi></sense></entryFree>')
        self.assertEqual(name_gloss(e, 'Abbassus'), 'a town in Phrygia')
        e = ('<entryFree key="Abellinum"><sense n="I"><hi rend="ital">Abellinum, a city of the Hirpini</hi></sense></entryFree>')
        self.assertEqual(name_gloss(e, 'Abellīnum'), 'a city of the Hirpini')
        e = ('<entryFree key="Ops"><sense n="I"><hi rend="ital">nom. sing.</hi> <hi rend="ital">a personification</hi></sense></entryFree>')
        self.assertEqual(name_gloss(e, 'Ops'), 'a personification')

    def test_nothing_when_the_entry_has_no_definition_in_italics(self):
        e = '<entryFree key="Sicilia"><orth>Sĭcĭlĭa</orth>, ae, f., = Σικελία, Sicily, Cic.</entryFree>'
        self.assertEqual(name_gloss(e, 'Sĭcĭlĭa'), '')
        e = '<entryFree key="Cotta"><sense n="I"><hi rend="ital">v. Aurelius</hi></sense></entryFree>'
        self.assertEqual(name_gloss(e, 'Cotta'), '')

    def test_ligatures_are_expanded(self):
        e = '<entryFree key="Antigone"><sense n="I"><hi rend="ital">a daughter of the Theban king Œdipus</hi></sense></entryFree>'
        self.assertEqual(name_gloss(e, 'Antĭgŏnē'), 'a daughter of the Theban king Oedipus')

    def test_a_name_is_capitalised_and_a_word_is_not(self):
        self.assertTrue(is_name_entry('Tīmarchĭdes')); self.assertTrue(is_name_entry('-Que2'))
        self.assertFalse(is_name_entry('stella')); self.assertFalse(is_name_entry('ăb'))
        self.assertFalse(is_name_entry('L'))       # the letter, not a name

    def test_names_get_their_own_cap(self):
        g = 'a daughter of the Athenian king Erechtheus, wife of Cephalus'
        self.assertEqual(enforce(name_clean(g), NAME_MAXWORDS),
                         'daughter of the Athenian king Erechtheus, wife of Cephalus')
        self.assertGreater(NAME_MAXWORDS, 5)

    def test_the_name_cleaner_keeps_initials_and_drops_clauses(self):
        # the general cleaner read "Q." as a citation and left "of"
        self.assertEqual(name_clean('of Q. Lutatius Catulus'), 'of Q. Lutatius Catulus')
        self.assertEqual(name_clean('adj., of or belonging to M. Pescennius Niger, the rival of Septimius Severus'),
                         'of or belonging to M. Pescennius Niger')
        self.assertEqual(name_clean('the Hyades, a group of seven stars in the head of Taurus', headword='Hўădes'),
                         'group of seven stars in the head of Taurus')
        self.assertEqual(name_clean('a Roman praenomen, abbreviated T.'), 'Roman praenomen')
        self.assertEqual(name_clean('a celebrated philosopher of Samos, about 550 B.C.'), 'celebrated philosopher of Samos')
        self.assertEqual(name_clean('a famous heretic of the fifth century A. D.'), 'famous heretic of the fifth century')
        self.assertEqual(name_clean('a Roman emperor, reigned between 69 and 79 A. D.'), 'Roman emperor')
        self.assertEqual(name_clean('tutelar deities, Lares, belonging orig. to the Etruscan religion'),
                         'tutelar deities, Lares, belonging to the Etruscan religion')
        # a relative clause is a sentence about the name, not a gloss of it
        self.assertEqual(name_clean('A king of the Caeninenses, who, in the war with the Romans, was slain'),
                         'king of the Caeninenses')
        self.assertEqual(name_clean('a Roman emperor who reigned A.D. 270-275'), 'Roman emperor')
        self.assertEqual(name_clean('a Roman cognomen in the gens Tullia'), 'Roman surname in the gens Tullia')

    def test_a_plural_echo_is_skipped_and_a_quotation_ignored(self):
        e = ('<entryFree key="Amazon"><sense n="I"><hi rend="ital">an Amazon;</hi> and plur., '
             '<hi rend="ital">Amazons</hi>, <hi rend="ital">warlike women</hi></sense></entryFree>')
        self.assertEqual(name_gloss(e, 'Ămāzon'), 'warlike women')
        e = ('<entryFree key="Cyclops"><sense n="I"><hi rend="ital">a Cyclops;</hi> in plur.: <cit><quote>Cyclopes</quote> '
             '<trans><tr><hi rend="ital">the Cyclopes, a fabulous race</hi></tr></trans></cit></sense></entryFree>')
        self.assertEqual(name_gloss(e, 'Cyclops'), '')
        e = '<entryFree key="Enipeus"><sense n="I"><hi rend="ital">a river in Thessaly that flows into the Penēus</hi></sense></entryFree>'
        self.assertEqual(name_gloss(e, 'Ĕnīpeus'), 'a river in Thessaly that flows into the Peneus')


class TestNamesInTheOfflineRebuild(unittest.TestCase):
    """End to end: a name entry ships the dictionary's words with source `ls`
    and a longer cap; one with no italic keeps the model's gloss."""

    def test_offline_run(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ck = [{'i': 0, 'g': 'Athenian sculptor', 'p': 'main'},
                  {'i': 1, 'g': 'Sicily', 'p': 'main'},
                  {'i': 2, 'g': 'Athenian courtesan', 'p': 'main'},
                  {'i': 3, 'g': 'star', 'p': 'main'}]
            (d / 'c.jsonl').write_text('\n'.join(json.dumps(x) for x in ck) + '\n', encoding='utf-8')
            proc = subprocess.run([sys.executable, str(ROOT / 'lsgloss.py'), '--xml', str(FIX / 'mini_name.xml'),
                                   '--out', str(d / 'o.tsv'), '--ckpt', str(d / 'c.jsonl'),
                                   '--url', 'http://127.0.0.1:9/', '--offline'],
                                  capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            rows = {}
            for line in (d / 'o.tsv').read_text(encoding='utf-8').splitlines():
                if not line.startswith('#'):
                    f = line.split('\t'); rows[f[0]] = f
        self.assertEqual(rows['Timarchides'][2:4], ['sculptor', 'ls'])
        self.assertEqual(rows['Procris'][2], 'daughter of the Athenian king Erechtheus, wife of Cephalus')
        self.assertEqual(rows['Procris'][3], 'ls')
        self.assertEqual(rows['Sicilia'][2:4], ['Sicily', 'model'])
        self.assertEqual(rows['stella'][2:4], ['star', 'model'])


class TestFunctionWordGlosses(unittest.TestCase):
    """The commonest words in Vergil and Caesar shipped grammar-book frames:
    `nec` "inseparable negative particle", `ab` "departure from a fixed point",
    `de` "of place, down", `uti` "use of utor", `animus` "Graeco-Italic form
    of wind", `tamen` "tamen, nevertheless"."""

    def test_a_frame_is_a_word_class_description(self):
        self.assertIn('word-class', reasons('nec', 'inseparable negative particle', 'hard', 'nec, an inseparable particle'))
        self.assertIn('word-class', reasons('ab', 'departure from a fixed point', 'freqfix', 'ab, praep. with abl. from'))
        self.assertIn('word-class', reasons('de', 'of place, down', 'model', 'de, praep. with abl. from'))
        self.assertIn('word-class', reasons('uti', 'use of utor', 'model', 'uti, conj. v. ut'))
        self.assertNotIn('word-class', reasons('ab', 'from, away from', 'model', 'ab, praep. with abl. from'))

    def test_a_provenance_note_is_not_a_gloss(self):
        self.assertIn('form-note', reasons('animus', 'Graeco‑Italic form of wind', 'repaired', 'animus, i, m. the soul'))
        self.assertIn('form-note', reasons('geno', 'old form of gigno', 'model', 'geno, old form of gigno'))
        self.assertNotIn('form-note', reasons('arcuatim', 'form of a bow', 'model', 'arcuatim, adv. in the form of a bow'))

    def test_a_headword_echo_in_front_of_a_gloss_is_stripped(self):
        self.assertEqual(strip_head_echo('tamen', 'tamen, nevertheless, however, still', {}), 'nevertheless, however, still')
        # an English cognate other entries use stays: "orator, speaker"
        self.assertEqual(strip_head_echo('orator', 'orator, speaker', {'orator': 3}), 'orator, speaker')
        # never empties a gloss
        self.assertEqual(strip_head_echo('tamen', 'tamen', {}), 'tamen')


if __name__ == '__main__':
    unittest.main()
