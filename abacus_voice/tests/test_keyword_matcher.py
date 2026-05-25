"""
Testy jednostkowe dla KeywordMatcher.
Nie wymagają Frappe ani zewnętrznych API.

Uruchomienie (bez Frappe):
    python -m pytest abacus_voice/tests/test_keyword_matcher.py -v
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import unittest
from abacus_voice.engine.keyword_matcher import KeywordMatcher, normalize


NODE = {
    "keywords_yes": ["tak", "już", "wysłałem", "dostarczyłem", "oczywiście", "zgadza się"],
    "keywords_no": ["nie", "jeszcze", "czekam", "brakuje", "problem"],
    "keywords_optout": ["nie dzwoń", "usuń", "wypisz", "stop"],
}

NODE_NO_OPTOUT = {
    "keywords_yes": ["tak"],
    "keywords_no": ["nie"],
}


class TestNormalize(unittest.TestCase):

    def test_lowercase(self):
        self.assertEqual(normalize("TAK"), "tak")

    def test_strip_diacritics(self):
        self.assertEqual(normalize("już"), "juz")
        self.assertEqual(normalize("dostarczyłem"), "dostarczylem")
        self.assertEqual(normalize("brakuje"), "brakuje")

    def test_strip_punctuation(self):
        self.assertEqual(normalize("tak!"), "tak")
        self.assertEqual(normalize("nie, jeszcze..."), "nie jeszcze")

    def test_multiple_spaces(self):
        self.assertEqual(normalize("tak  już"), "tak juz")


class TestKeywordMatcherYes(unittest.TestCase):

    def test_simple_tak(self):
        self.assertEqual(KeywordMatcher.match("tak", NODE), "yes")

    def test_uppercase_TAK(self):
        self.assertEqual(KeywordMatcher.match("TAK", NODE), "yes")

    def test_juz_in_sentence(self):
        self.assertEqual(KeywordMatcher.match("Tak, już wysłałem wczoraj", NODE), "yes")

    def test_oczywiscie(self):
        self.assertEqual(KeywordMatcher.match("Oczywiście, zrobiłem to", NODE), "yes")

    def test_wyslałem_with_diacritics(self):
        self.assertEqual(KeywordMatcher.match("wysłałem dokumenty", NODE), "yes")


class TestKeywordMatcherNo(unittest.TestCase):

    def test_simple_nie(self):
        self.assertEqual(KeywordMatcher.match("nie", NODE), "no")

    def test_jeszcze_nie(self):
        self.assertEqual(KeywordMatcher.match("jeszcze nie", NODE), "no")

    def test_czekam(self):
        self.assertEqual(KeywordMatcher.match("czekam na jeden dokument", NODE), "no")

    def test_problem_sentence(self):
        self.assertEqual(
            KeywordMatcher.match("Wiesz, mam problem bo brakuje mi jednego", NODE),
            "no"
        )


class TestKeywordMatcherOptout(unittest.TestCase):

    def test_nie_dzwon(self):
        self.assertEqual(KeywordMatcher.match("nie dzwoń do mnie", NODE), "optout")

    def test_usun(self):
        self.assertEqual(KeywordMatcher.match("usuń mnie z listy", NODE), "optout")

    def test_stop(self):
        self.assertEqual(KeywordMatcher.match("stop", NODE), "optout")

    def test_optout_beats_no(self):
        """Optout ma wyższy priorytet niż no."""
        node_with_overlap = {
            "keywords_yes": ["tak"],
            "keywords_no": ["nie"],
            "keywords_optout": ["nie dzwoń"],
        }
        # "nie dzwoń" zawiera "nie" (no) ale powinno dać optout
        self.assertEqual(
            KeywordMatcher.match("proszę nie dzwoń więcej", node_with_overlap),
            "optout"
        )


class TestKeywordMatcherNone(unittest.TestCase):

    def test_unclear_response(self):
        self.assertIsNone(KeywordMatcher.match("no właśnie kwestia jest taka", NODE))

    def test_empty_string(self):
        self.assertIsNone(KeywordMatcher.match("", NODE))

    def test_whitespace_only(self):
        self.assertIsNone(KeywordMatcher.match("   ", NODE))

    def test_unrelated_sentence(self):
        self.assertIsNone(KeywordMatcher.match("kiedy będzie rozliczenie PIT", NODE))

    def test_no_keywords_in_node(self):
        self.assertIsNone(KeywordMatcher.match("tak", {}))


class TestCaptureValue(unittest.TestCase):

    def test_captures_text(self):
        self.assertEqual(KeywordMatcher.capture_value("do piątku"), "do piątku")

    def test_strips_whitespace(self):
        self.assertEqual(KeywordMatcher.capture_value("  do poniedziałku  "), "do poniedziałku")

    def test_empty(self):
        self.assertEqual(KeywordMatcher.capture_value(""), "")


if __name__ == "__main__":
    unittest.main()
