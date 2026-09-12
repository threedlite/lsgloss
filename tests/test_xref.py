"""is_xref decides what never reaches the model.

A false positive silently blanks a real definition; a false negative spends a
model call and then emits XREF. The hard case is that "v." abbreviates both
*vide* ("see") and *verbum* (the part-of-speech marker).
"""
import unittest
from tests.util import ROOT
from eval.xref import is_xref


class TestPositives(unittest.TestCase):
    def test_bare_see_reference(self):
        self.assertTrue(is_xref('inspargo, insparsus, v. inspergo.'))

    def test_reference_with_trailing_section_pointer(self):
        self.assertTrue(is_xref('abditē, adv., v. abdo, P. a. fin.'))
        self.assertTrue(is_xref('grātīs, adv., v. gratia, B. fin.'))

    def test_reference_with_parenthetical_spelling_variant(self):
        self.assertTrue(is_xref('condĭtĭo (condition, etc.), v. condicio, etc.'))

    def test_participle_pointing_at_its_verb(self):
        self.assertTrue(is_xref('sēcrētus, a, um, Part. and P. a., from secerno.'))
        self.assertTrue(is_xref('ăbactus, a, um, Part. of abigo, q. v.'))


class TestNegatives(unittest.TestCase):
    def test_v_as_verbum_is_not_a_reference(self):
        # "v. freq. a." marks a frequentative verb; the entry then defines itself
        self.assertFalse(is_xref('ab-brĕvĭo, āre, v. freq. a. ... to shorten'))

    def test_a_real_definition_is_not_a_reference(self):
        self.assertFalse(is_xref('stellŭla, ae, f. dim. a little star'))

    def test_long_entries_are_never_cross_references(self):
        # every long article cites something; length alone rules it out
        self.assertFalse(is_xref('x, ' + ('word ' * 60) + ', v. something.'))


if __name__ == '__main__':
    unittest.main()
