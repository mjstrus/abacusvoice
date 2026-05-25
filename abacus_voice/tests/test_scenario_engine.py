"""
Testy jednostkowe dla ScenarioEngine.
Mockują ClaudeFallback i SessionManager — nie wymagają Frappe ani API.

Uruchomienie (bez Frappe):
    python -m pytest abacus_voice/tests/test_scenario_engine.py -v
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import json
import unittest
from unittest.mock import patch

from abacus_voice.engine.scenario_engine import (
    ScenarioEngine, DecisionResult,
    ACTION_END, ACTION_GOTO, ACTION_OPTOUT, ACTION_UNCLEAR, ACTION_DIGRESSION,
    render_jinja,
)


# Scenariusz testowy
SCENARIO_JSON = json.dumps({
    "opening": "Dzień dobry, {{ client_name }}. Czy dostarczyłeś dokumenty?",
    "nodes": {
        "q1": {
            "keywords_yes": ["tak", "już"],
            "keywords_no": ["nie", "jeszcze", "problem"],
            "keywords_optout": ["nie dzwoń", "usuń"],
            "on_yes": {
                "say": "Dziękuję, miłego dnia!",
                "action": "end",
                "extract": {"result": "TAK"},
            },
            "on_no": {
                "say": "Rozumiem. Do którego dnia dostarczysz komplet?",
                "action": "goto",
                "next": "q2",
            },
            "on_unclear": "claude_fallback",
        },
        "q2": {
            "capture_as": "deadline",
            "say_template": "Dziękuję, zanotowałem. Do zobaczenia!",
            "action": "end",
            "extract": {"result": "NIE", "deadline": "{{captured}}"},
        },
    },
    "closing_optout": "Rozumiem, nie będziemy dzwonić. Do widzenia.",
    "closing_error": "Skontaktuje się z Tobą pracownik biura.",
}, ensure_ascii=False)

CONTEXT_DATA = {"client_name": "Jan Kowalski", "kwota": "1500"}

BASE_SESSION = {
    "scenario_id": "Dokumenty Check",
    "scenario_data": json.loads(SCENARIO_JSON),
    "current_node": "q1",
    "history": [],
    "digression_used": False,
    "context_data": CONTEXT_DATA,
    "client_id": "KLIENT-001",
    "attempt": 1,
    "opt_out": False,
    "extracted_data": {},
}


def _fresh_session():
    import copy
    return copy.deepcopy(BASE_SESSION)


def _make_engine():
    return ScenarioEngine.from_rendered_json(SCENARIO_JSON, CONTEXT_DATA)


class TestRenderJinja(unittest.TestCase):

    def test_renders_client_name(self):
        result = render_jinja("Dzień dobry, {{ client_name }}.", {"client_name": "Jan Kowalski"})
        self.assertEqual(result, "Dzień dobry, Jan Kowalski.")

    def test_renders_kwota(self):
        result = render_jinja("Zaległość: {{ kwota }} zł.", {"kwota": "1500"})
        self.assertEqual(result, "Zaległość: 1500 zł.")

    def test_unknown_variable_ignored(self):
        """Nieznana zmienna nie powoduje błędu — zostaje pusta."""
        result = render_jinja("Witaj, {{ nieznana }}.", {})
        self.assertIn("Witaj", result)

    def test_no_placeholders(self):
        result = render_jinja("Czy dostarczyłeś dokumenty?", {})
        self.assertEqual(result, "Czy dostarczyłeś dokumenty?")


class TestScenarioEngineFromJson(unittest.TestCase):

    def test_opening_rendered(self):
        engine = _make_engine()
        self.assertIn("Jan Kowalski", engine.get_opening_text())

    def test_first_node_is_q1(self):
        engine = _make_engine()
        self.assertIn("q1", engine.nodes)


class TestScenarioEngineYes(unittest.TestCase):

    def test_tak_returns_end(self):
        engine = _make_engine()
        session = _fresh_session()
        result, updated = engine.process_response("tak", session)
        self.assertEqual(result.action, ACTION_END)
        self.assertEqual(result.extracted_data.get("result"), "TAK")

    def test_juz_wyslałem_returns_end(self):
        engine = _make_engine()
        session = _fresh_session()
        result, _ = engine.process_response("Tak, już wysłałem wczoraj", session)
        self.assertEqual(result.action, ACTION_END)

    def test_say_text_present(self):
        engine = _make_engine()
        session = _fresh_session()
        result, _ = engine.process_response("tak", session)
        self.assertIn("Dziękuję", result.say_text)


class TestScenarioEngineNo(unittest.TestCase):

    def test_nie_returns_goto_q2(self):
        engine = _make_engine()
        session = _fresh_session()
        result, updated = engine.process_response("nie", session)
        self.assertEqual(result.action, ACTION_GOTO)
        self.assertEqual(result.next_node, "q2")

    def test_problem_returns_goto(self):
        engine = _make_engine()
        session = _fresh_session()
        result, _ = engine.process_response("mam problem z jednym dokumentem", session)
        self.assertEqual(result.action, ACTION_GOTO)

    def test_session_node_updated(self):
        engine = _make_engine()
        session = _fresh_session()
        _, updated = engine.process_response("nie", session)
        self.assertEqual(updated["current_node"], "q2")


class TestScenarioEngineCaptureNode(unittest.TestCase):

    def test_q2_captures_deadline(self):
        """Węzeł q2 z capture_as powinien zapisać odpowiedź klienta."""
        engine = _make_engine()
        session = _fresh_session()
        session["current_node"] = "q2"
        result, updated = engine.process_response("do piątku", session)
        self.assertEqual(result.action, ACTION_END)
        self.assertEqual(updated["extracted_data"].get("deadline"), "do piątku")
        self.assertEqual(updated["extracted_data"].get("result"), "NIE")

    def test_q2_say_template(self):
        engine = _make_engine()
        session = _fresh_session()
        session["current_node"] = "q2"
        result, _ = engine.process_response("do wtorku", session)
        self.assertIn("Dziękuję", result.say_text)


class TestScenarioEngineOptout(unittest.TestCase):

    def test_nie_dzwon_sets_optout(self):
        engine = _make_engine()
        session = _fresh_session()
        result, updated = engine.process_response("nie dzwoń do mnie", session)
        self.assertEqual(result.action, ACTION_OPTOUT)
        self.assertTrue(updated["opt_out"])

    def test_optout_say_text(self):
        engine = _make_engine()
        session = _fresh_session()
        result, _ = engine.process_response("usuń mnie z listy", session)
        self.assertIn("nie będziemy dzwonić", result.say_text)


class TestScenarioEngineDigression(unittest.TestCase):

    @patch("abacus_voice.engine.scenario_engine.ClaudeFallback.decide")
    def test_first_digression_sets_flag(self, mock_claude):
        """Pierwsza dygresja: Claude odpowiada, digression_used=True."""
        mock_claude.return_value = {
            "action": "digression",
            "next_node": None,
            "extracted_data": {},
            "digression_response": "PIT będzie gotowy w marcu.",
            "say_text": None,
        }
        engine = _make_engine()
        session = _fresh_session()
        result, updated = engine.process_response("kiedy będzie PIT?", session)
        self.assertEqual(result.action, ACTION_DIGRESSION)
        self.assertTrue(updated["digression_used"])
        self.assertIn("PIT", result.say_text)

    @patch("abacus_voice.engine.scenario_engine.ClaudeFallback.decide")
    def test_second_digression_ignored(self, mock_claude):
        """Druga dygresja: Claude zwraca unclear, system wraca do scenariusza."""
        mock_claude.return_value = {
            "action": "unclear",
            "next_node": None,
            "extracted_data": {},
            "digression_response": None,
            "say_text": None,
        }
        engine = _make_engine()
        session = _fresh_session()
        session["digression_used"] = True  # Limit już wyczerpany
        result, _ = engine.process_response("a co z VAT-em?", session)
        # Powinien wrócić do scenariusza, nie odpowiadać na dygresję
        self.assertNotEqual(result.action, ACTION_DIGRESSION)


class TestScenarioEngineHistory(unittest.TestCase):

    def test_history_updated_after_turn(self):
        engine = _make_engine()
        session = _fresh_session()
        _, updated = engine.process_response("tak", session)
        history = updated["history"]
        # Powinna być przynajmniej 1 tura klienta i 1 systemu
        speakers = [t["speaker"] for t in history]
        self.assertIn("client", speakers)
        self.assertIn("system", speakers)

    def test_client_text_in_history(self):
        engine = _make_engine()
        session = _fresh_session()
        _, updated = engine.process_response("tak", session)
        client_turns = [t for t in updated["history"] if t["speaker"] == "client"]
        self.assertEqual(client_turns[0]["text"], "tak")


if __name__ == "__main__":
    unittest.main()
