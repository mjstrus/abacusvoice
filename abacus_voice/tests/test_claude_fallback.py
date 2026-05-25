"""
Testy jednostkowe dla ClaudeFallback.
Mockują Claude API — nie wymagają prawdziwego klucza API.

Uruchomienie (bez Frappe):
    python -m pytest abacus_voice/tests/test_claude_fallback.py -v
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import json
import unittest
from unittest.mock import patch, MagicMock


SCENARIO_DATA = {
    "opening": "Czy dostarczyłeś dokumenty?",
    "nodes": {
        "q1": {
            "keywords_yes": ["tak"],
            "keywords_no": ["nie"],
            "keywords_optout": ["nie dzwoń"],
            "on_yes": {"say": "Dziękuję!", "action": "end", "extract": {"result": "TAK"}},
            "on_no": {"say": "Do kiedy?", "action": "goto", "next": "q2"},
            "on_unclear": "claude_fallback",
        }
    },
    "closing_optout": "Rozumiem, do widzenia.",
    "closing_error": "Skontaktuje się z Tobą pracownik biura.",
}

HISTORY = [
    {"speaker": "system", "text": "Czy dostarczyłeś dokumenty?"},
]


def _make_mock_response(action, next_node=None, say_text=None, digression_response=None):
    """Buduje mock odpowiedzi Claude."""
    payload = {
        "action": action,
        "next_node": next_node,
        "extracted_data": {},
        "digression_response": digression_response,
        "say_text": say_text,
    }
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=json.dumps(payload))]
    return mock_message


class TestClaudeFallback(unittest.TestCase):

    def _get_settings_mock(self):
        mock_settings = MagicMock()
        mock_settings.get_password.return_value = "test-api-key"
        return mock_settings

    @patch("abacus_voice.engine.claude_fallback.frappe")
    @patch("abacus_voice.engine.claude_fallback.anthropic.Anthropic")
    def test_unclear_ambiguous_response(self, mock_anthropic_cls, mock_frappe):
        """Niejasna odpowiedź → Claude zwraca action=no."""
        mock_frappe.get_single.return_value = self._get_settings_mock()

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _make_mock_response(
            action="no", say_text="Do kiedy dostarczysz dokumenty?"
        )

        from abacus_voice.engine.claude_fallback import ClaudeFallback
        result = ClaudeFallback.decide(
            scenario_data=SCENARIO_DATA,
            current_node_id="q1",
            speech_text="Wiesz, mam problem bo brakuje mi jednego dokumentu",
            history=HISTORY,
            digression_used=False,
        )

        self.assertEqual(result["action"], "no")
        self.assertEqual(result["say_text"], "Do kiedy dostarczysz dokumenty?")

    @patch("abacus_voice.engine.claude_fallback.frappe")
    @patch("abacus_voice.engine.claude_fallback.anthropic.Anthropic")
    def test_digression_first_time(self, mock_anthropic_cls, mock_frappe):
        """Pierwsza dygresja → Claude zwraca action=digression z odpowiedzią."""
        mock_frappe.get_single.return_value = self._get_settings_mock()

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _make_mock_response(
            action="digression",
            digression_response="Rozliczenie PIT będzie gotowe w marcu.",
        )

        from abacus_voice.engine.claude_fallback import ClaudeFallback
        result = ClaudeFallback.decide(
            scenario_data=SCENARIO_DATA,
            current_node_id="q1",
            speech_text="Kiedy będzie rozliczenie PIT?",
            history=HISTORY,
            digression_used=False,
        )

        self.assertEqual(result["action"], "digression")
        self.assertIn("PIT", result["digression_response"])

    @patch("abacus_voice.engine.claude_fallback.frappe")
    @patch("abacus_voice.engine.claude_fallback.anthropic.Anthropic")
    def test_digression_already_used_returns_unclear(self, mock_anthropic_cls, mock_frappe):
        """Druga dygresja gdy limit wyczerpany → Claude otrzymuje notatkę, zwraca unclear."""
        mock_frappe.get_single.return_value = self._get_settings_mock()

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _make_mock_response(action="unclear")

        from abacus_voice.engine.claude_fallback import ClaudeFallback
        result = ClaudeFallback.decide(
            scenario_data=SCENARIO_DATA,
            current_node_id="q1",
            speech_text="A co z VAT-em?",
            history=HISTORY,
            digression_used=True,  # limit wyczerpany
        )

        self.assertEqual(result["action"], "unclear")
        # Sprawdź że prompt zawierał notatkę o limicie dygresji
        call_args = mock_client.messages.create.call_args
        user_content = call_args[1]["messages"][0]["content"]
        self.assertIn("limit dygresji", user_content)

    @patch("abacus_voice.engine.claude_fallback.frappe")
    @patch("abacus_voice.engine.claude_fallback.anthropic.Anthropic")
    def test_invalid_json_response_returns_unclear(self, mock_anthropic_cls, mock_frappe):
        """Gdy Claude zwróci nieprawidłowy JSON → _unclear_result."""
        mock_frappe.get_single.return_value = self._get_settings_mock()

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        bad_message = MagicMock()
        bad_message.content = [MagicMock(text="to nie jest json")]
        mock_client.messages.create.return_value = bad_message

        from abacus_voice.engine.claude_fallback import ClaudeFallback
        result = ClaudeFallback.decide(
            scenario_data=SCENARIO_DATA,
            current_node_id="q1",
            speech_text="hmmm",
            history=HISTORY,
            digression_used=False,
        )

        self.assertEqual(result["action"], "unclear")

    @patch("abacus_voice.engine.claude_fallback.frappe")
    @patch("abacus_voice.engine.claude_fallback.anthropic.Anthropic")
    def test_api_error_returns_unclear(self, mock_anthropic_cls, mock_frappe):
        """Gdy Claude API rzuci wyjątek → _unclear_result."""
        import anthropic as anthropic_module
        mock_frappe.get_single.return_value = self._get_settings_mock()

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.side_effect = anthropic_module.APIConnectionError(
            request=MagicMock()
        )

        from abacus_voice.engine.claude_fallback import ClaudeFallback
        result = ClaudeFallback.decide(
            scenario_data=SCENARIO_DATA,
            current_node_id="q1",
            speech_text="nie wiem",
            history=HISTORY,
            digression_used=False,
        )

        self.assertEqual(result["action"], "unclear")


if __name__ == "__main__":
    unittest.main()
