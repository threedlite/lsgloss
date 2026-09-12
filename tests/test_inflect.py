"""Paradigm generation is the largest single contributor to coverage.

README: "gloss defects affect ~1% of tokens while missing coverage affected
50%". A paradigm that stops generating a form does not raise -- the reader just
gets nothing under that word -- so these tests assert real forms are present,
not merely that the function returns something.
"""
import unittest
from tests.util import ROOT
from inflect import (forms_for, forms_with_morph, postag_morph, pos_from_entry,
                     render_morph, render_readings, split_enclitic,
                     _noun_stem_and_key, SLOT_ORDER, SLOT_VALUES)


def forms(head, body):
    return forms_for(head, body)


class TestNounParadigms(unittest.TestCase):
    def test_first_declension(self):
        f = forms('porta', 'porta, ae, f. a gate')
        self.assertLessEqual({'porta', 'portae', 'portam', 'portas', 'portarum', 'portis'}, f)

    def test_second_declension(self):
        # generated forms are word_form keys, so they come out folded: seru-, not serv-
        f = forms('servus', 'servus, i, m. a slave')
        self.assertLessEqual({'seruus', 'serui', 'seruo', 'seruum', 'seruorum'}, f)

    def test_third_declension_uses_the_oblique_stem(self):
        f = forms('rex', 'rex, regis, m. a king')
        self.assertLessEqual({'rex', 'regis', 'regem', 'reges', 'regum', 'regibus'}, f)

    def test_third_declension_abbreviated_genitive(self):
        # "corpus, oris" is corpOris: the real stem is corpor-, not or-
        stem, key = _noun_stem_and_key('corpus', 'oris')
        self.assertEqual((stem, key), ('corpor', 'is'))

    def test_fourth_declension(self):
        f = forms('manus', 'manus, us, f. a hand')
        self.assertLessEqual({'manus', 'manui', 'manum', 'manuum', 'manibus'}, f)


class TestVerbParadigms(unittest.TestCase):
    def test_first_conjugation(self):
        # the perfect comes out folded (amauit, not amavit) because every
        # generated form is a word_form key -- see forms_for
        f = forms('amo', 'amo, avi, atum, 1, v. a. to love')
        self.assertLessEqual({'amo', 'amat', 'amant', 'amauit', 'amare', 'amatus'}, f)

    def test_fourth_conjugation_drops_the_stem_i(self):
        # endings already carry their i (io, is, it), so audio -> aud-, not audi-
        f = forms('audio', 'audio, ivi, itum, 4, v. a. to hear')
        self.assertIn('audit', f)
        self.assertNotIn('audiit', f)


class TestCompoundGuard(unittest.TestCase):
    def test_compound_does_not_claim_the_simple_words_paradigm(self):
        # "vigintivir, viri" abbreviates vigintiviri; taken literally the
        # compound would own virum, viri, virorum
        f = forms('vigintivir', 'vigintivir, viri, m. one of a board of twenty')
        self.assertNotIn('virorum', f)
        self.assertNotIn('virum', f)


class TestEnclitics(unittest.TestCase):
    def test_splits_que(self):
        self.assertEqual(split_enclitic('armaque'), ('arma', 'que'))

    def test_splits_ve(self):
        self.assertEqual(split_enclitic('bonave'), ('bona', 've'))

    def test_requires_a_stem_of_at_least_four_letters(self):
        # 'duove' is left whole: a 3-letter stem is as likely to be a real word
        # ending in -ve as a genuine enclitic
        self.assertEqual(split_enclitic('duove'), ('duove', ''))

    def test_does_not_split_ne(self):
        # -ne collides with the ablative of every -io/-ionis noun
        self.assertEqual(split_enclitic('ratione'), ('ratione', ''))

    def test_does_not_split_a_short_word_into_nothing(self):
        self.assertEqual(split_enclitic('que'), ('que', ''))


class TestFoldedOutput(unittest.TestCase):
    def test_the_stem_is_folded(self):
        # every generated form is a word_form key, so i/j and u/v are merged
        f = forms('juvo', 'juvo, juvi, jutum, 1, v. a. to help')
        self.assertIn('iuuo', f)
        self.assertNotIn('juvo', f)

    def test_headword_is_always_present(self):
        self.assertIn('porta', forms('porta', 'porta, ae, f. a gate'))

    def test_forms_are_length_bounded(self):
        f = forms('amo', 'amo, avi, atum, 1, v. a. to love')
        self.assertTrue(all(2 <= len(w) <= 24 for w in f))




class TestMorphLabels(unittest.TestCase):
    """Every generated form knows which paradigm slot produced it.

    The slot is the only place the morphology exists: once the endings are
    applied and collected into a set, `portis` is a string and nothing
    downstream can recover that it is dative/ablative plural. morphology.csv
    shipped 1.5M rows saying `generated paradigm` for want of this.
    """

    def test_labels_cover_every_generated_form(self):
        m = forms_with_morph('porta', 'porta, ae, f. a gate')
        self.assertEqual(sorted(f for f, i in m.items() if not i), [])

    def test_forms_for_still_returns_the_same_set(self):
        args = ('amo', 'amo, avi, atum, 1, v. a. to love')
        self.assertEqual(forms_for(*args), set(forms_with_morph(*args)))

    def test_noun_endings_name_their_cases(self):
        m = forms_with_morph('porta', 'porta, ae, f. a gate')
        self.assertEqual(m['portarum'], 'gen p f')
        self.assertEqual(m['portis'], 'abl p f|dat p f')

    def test_an_ambiguous_ending_names_every_case_it_can_be(self):
        # -ae is genitive singular, dative singular and nominative plural at
        # once; picking one would be a guess presented as a fact
        # every reading in full, not one underspecified blur: "s/p gen/dat/nom"
        # would also admit `nom s` and `gen p`, which -ae never is
        m = forms_with_morph('porta', 'porta, ae, f. a gate')
        # no locative: it survives for place names, not for a gate
        self.assertEqual(m['portae'], 'dat s f|gen s f|nom p f|voc p f')

    def test_verb_endings_name_person_tense_and_mood(self):
        m = forms_with_morph('amo', 'amo, avi, atum, 1, v. a. to love')
        self.assertEqual(m['amat'], '3 s pres active ind')
        self.assertEqual(m['amauit'], '3 s perf active ind')
        self.assertEqual(m['amare'],
                         '0 pres active inf|2 s pres passive imp|2 s pres passive ind')

    def test_the_headword_only_falls_back_when_no_slot_claims_it(self):
        # porta IS the nominative singular, so it keeps the paradigm's reading;
        # rex is not generated by the 3rd-declension table, which builds from the
        # oblique stem, so the entry's part of speech is all it has
        self.assertEqual(forms_with_morph('porta', 'porta, ae, f. a gate')['porta'],
                         'abl s f|nom s f|voc s f')
        self.assertEqual(forms_with_morph('rex', 'rex, regis, m. a king')['rex'],
                         'nom s m')

    def test_labels_do_not_depend_on_iteration_order(self):
        args = ('porta', 'porta, ae, f. a gate')
        self.assertEqual(forms_with_morph(*args), forms_with_morph(*args))


class TestPostagMorph(unittest.TestCase):
    """Perseus treebanks carry a parse per token; the package used to drop it."""

    def test_verb(self):
        self.assertEqual(postag_morph('v3spip---'), '3 s pres passive ind')

    def test_participle_keeps_gender_and_case(self):
        self.assertEqual(postag_morph('v-sppamn-'), 'nom s m pres active part')

    def test_noun(self):
        # no part-of-speech token: a noun is described by its case, as in the
        # 1.96M Whitaker rows this sits beside
        self.assertEqual(postag_morph('n-s---mn-'), 'nom s m')

    def test_a_tag_with_one_slot_filled(self):
        self.assertEqual(postag_morph('d--------'), 'adv')

    def test_a_pronoun_keeps_its_token(self):
        self.assertEqual(postag_morph('p-s---md-'), 'dat s m pron')

    def test_empty_and_unparseable_tags_say_nothing(self):
        # the Greek treebanks use values the Latin tagset does not; an unknown
        # slot is skipped rather than guessed at
        self.assertEqual(postag_morph(''), '')
        self.assertEqual(postag_morph('---------'), '')
        self.assertEqual(postag_morph('zzzzzzzzz'), '')

    def test_a_short_tag_does_not_raise(self):
        self.assertEqual(postag_morph('v3s'), '3 s')




class TestOneSchema(unittest.TestCase):
    """morph_info is not free text. Every value, whatever produced it, is filled
    slots in one fixed order from one closed vocabulary per slot.

    The first attempt at this shipped two vocabularies at once: `est` came from
    the treebank as "verb 3 s pres act ind" while `amat` came from the paradigm
    tables as "3 s pres act ind", and `regis` as "noun s m gen" against `portis`
    as "dat/abl p" -- the same facts, different words, opposite slot order.
    """

    CASES = [
        ('porta', 'porta, ae, f. a gate'),
        ('rex', 'rex, regis, m. a king'),
        ('manus', 'manus, us, f. a hand'),
        ('res', 'res, rei, f. a thing'),
        ('amo', 'amo, avi, atum, 1, v. a. to love'),
        ('audio', 'audio, ivi, itum, 4, v. a. to hear'),
        ('moneo', 'moneo, ui, itum, 2, v. a. to warn'),
        ('ab', 'ab, prep. with abl., from'),
        ('pertinenter', 'pertinenter, adv., v. pertineo fin.'),
    ]

    def _slots(self, value):
        """Every reading in a value back into slots, by position."""
        out = []
        for reading in value.split('|'):
            pos = 0
            for token in reading.split():
                while pos < len(SLOT_ORDER):
                    slot = SLOT_ORDER[pos]; pos += 1
                    if token in SLOT_VALUES[slot]:
                        out.append((slot, token)); break
                else:
                    self.fail(f'{token!r} in {value!r} fits no slot, or is out of order')
        return out

    def test_every_generated_value_is_slots_in_order(self):
        for head, body in self.CASES:
            for form, value in forms_with_morph(head, body).items():
                if value:
                    self._slots(value)

    def test_no_part_of_speech_token_on_anything_that_inflects(self):
        # a noun row says "acc s f", never "noun" -- only the indeclinables
        # Whitaker skips carry a category
        for head, body in self.CASES[:7]:
            for value in forms_with_morph(head, body).values():
                for token in value.replace('|', ' ').split():
                    self.assertNotIn(token, ('noun', 'verb', 'adj', 'participle'))

    def test_every_treebank_tag_renders_into_the_same_schema(self):
        for tag in ['v3spia---', 'n-s---mg-', 'a-p---nb-', 't-srppnn-', 'd--------',
                    'v-pdpp---', 'p-s---md-', 'n-s---fv-', 'a-s---mns']:
            self._slots(postag_morph(tag))

    def test_the_treebank_and_the_paradigm_agree_on_wording(self):
        # the same fact from the two sources, written the same way
        self.assertEqual(postag_morph('v3spia---'),
                         forms_with_morph('amo', 'amo, avi, atum, 1, v. a.')['amat'])
        self.assertIn(postag_morph('n-p---fb-'),
                      forms_with_morph('porta', 'porta, ae, f.')['portis'].split('|'))

    def test_readings_are_sorted_so_a_rebuild_is_identical(self):
        v = render_readings([{'case': 'voc', 'number': 'p'},
                             {'case': 'dat', 'number': 's'},
                             {'case': 'gen', 'number': 's'}])
        self.assertEqual(v, 'dat s|gen s|voc p')

    def test_an_indeclinable_is_its_category_and_nothing_else(self):
        # Whitaker indexes no indeclinables at all -- ab, et, non, sed, cum, in,
        # ad have no row in the shipped database -- so these are ours alone and
        # nothing can disagree with them
        self.assertEqual(forms_with_morph('ab', 'ab, prep. with abl., from')['ab'],
                         'prep')
        self.assertEqual(forms_with_morph('atque', 'atque, conj., and')['atque'],
                         'conj')

    def test_a_value_outside_the_vocabulary_is_refused(self):
        # a typo in a paradigm table would otherwise ship as plausible-looking
        # morphology on a million rows
        for junk in [{'case': 'genitive'}, {'number': 'sing'}, {'tense': 'imperf'},
                     {'mood': 'subj'}, {'mood': 'gerund'}, {'mood': 'headword'},
                     {'case': 'treebank'}, {'category': 'noun'}]:
            with self.assertRaises(ValueError):
                render_morph(junk)


class TestPartOfSpeechFromEntry(unittest.TestCase):
    """L&S names the part of speech in the headword line; it fills the pos slot
    for the forms the paradigm tables cannot build."""

    def test_noun_gender(self):
        self.assertEqual(pos_from_entry('porta, ae, f. a gate'),
                         [{'pos': 'noun', 'gender': 'f'}])

    def test_verb(self):
        self.assertEqual(pos_from_entry('e-maculo, avi, atum, 1, v. a., to clear'),
                         [{'pos': 'verb'}])

    def test_deponent_verb(self):
        self.assertEqual(pos_from_entry('suppetior, atus, 1, v. dep. n., to assist'),
                         [{'pos': 'verb'}])

    def test_adjective(self):
        self.assertEqual(pos_from_entry('nemorosus, a, um, adj. nemus, woody'),
                         [{'pos': 'adj'}])

    def test_adverb_beats_the_verb_it_points_at(self):
        # "pertinenter, adv., v. pertineo" is an adverb; the `v.` is "see"
        self.assertEqual(pos_from_entry('pertinenter, adv., v. pertineo fin.'),
                         [{'pos': 'adv'}])

    def test_a_word_can_be_more_than_one_part_of_speech(self):
        # "inter, adv., and prep. with acc." is both, and keeping only the first
        # marker denied the other -- the largest single source of wrong readings
        # measured against the treebanks
        self.assertEqual(pos_from_entry('inter, adv., and prep. with acc.'),
                         [{'pos': 'adv'}, {'pos': 'prep'}])
        self.assertEqual(pos_from_entry('ne, conj. and adv., interj.'),
                         [{'pos': 'conj'}, {'pos': 'adv'}, {'pos': 'interj'}])

    def test_a_cross_reference_is_not_a_verb(self):
        # `v. concieo` means "see concieo" -- the commonest way to misread L&S.
        # The entry is an adjective that POINTS at a verb, and its own "a, um"
        # citation is what names it.
        self.assertEqual(pos_from_entry('concitus and concitus, a, um, v. concieo.'),
                         [{'pos': 'adj'}])

    def test_a_cross_reference_with_no_cue_at_all_names_nothing(self):
        self.assertEqual(pos_from_entry('Naevianus, v. 2. Naevius, B.'), [])
        self.assertEqual(pos_from_entry('liostrea, v. leiostrea.'), [])

    def test_an_adjective_cited_by_its_nominatives(self):
        self.assertEqual(pos_from_entry('phreniticus, a, um, v. phreneticus.'),
                         [{'pos': 'adj'}])

    def test_an_explicit_marker_beats_the_adjective_citation(self):
        # "interdictus, a, um, Part." is a participle; the "a, um" comes first
        # in the string but the marker is the thing L&S is actually asserting
        self.assertEqual(pos_from_entry('interdictus, a, um, Part., from interdico.'),
                         [{'pos': 'participle'}])

    def test_a_marker_behind_a_long_parenthesis_is_still_found(self):
        # L&S interrupts the headword line with variants and citations; the
        # marker can sit past any fixed window until they are dropped
        body = ('operio, ui, ertum, 4 (archaic fut. operibo: ego operibo caput, '
                'Pompon. ap. Non. 507, 33; imperf), v. a., to cover')
        self.assertEqual(pos_from_entry(body), [{'pos': 'verb'}])

    def test_participle(self):
        self.assertEqual(pos_from_entry('interdictus, a, um, Part., from interdico.'),
                         [{'pos': 'participle'}])

    def test_an_entry_naming_nothing_gets_nothing(self):
        self.assertEqual(pos_from_entry('abaddir, a stone swallowed by Saturn'), [])

    def test_the_definition_prose_is_not_searched(self):
        # "adv." appears freely in a long entry's prose; only the headword line
        # can name the part of speech
        body = 'nitor, oris, m. niteo, brightness' + ' x' * 200 + ', adv. '
        self.assertEqual(pos_from_entry(body), [{'pos': 'noun', 'gender': 'm'}])


if __name__ == '__main__':
    unittest.main()
