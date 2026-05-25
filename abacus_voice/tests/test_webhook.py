"""
Testy dla webhook handlers i NccoBuilder.

Strategia: testujemy logikę biznesową przez prywatne helpery (_handle_completed etc.)
oraz NccoBuilder w izolacji. Frappe dekorator @whitelist jest omijany przez
import modułu i wywołanie helperów bezpośrednio.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import json
import unittest
from unittest.mock import patch, MagicMock

from abacus_voice.ncco_builder import NccoBuilder


# ------------------------------------------------------------------
# Testy NccoBuilder (pure Python)
# ------------------------------------------------------------------

class TestNccoBuilder(unittest.TestCase):

    def test_talk_action(self):
        r = NccoBuilder.talk("Dzień dobry")
        self.assertEqual(r["action"], "talk")
        self.assertEqual(r["text"], "Dzień dobry")
        self.assertEqual(r["language"], "pl-PL")

    def test_talk_custom_language(self):
        r = NccoBuilder.talk("Hello", language="en-GB")
        self.assertEqual(r["language"], "en-GB")

    def test_input_speech_action(self):
        r = NccoBuilder.input_speech("https://example.com/asr")
        self.assertEqual(r["action"], "input")
        self.assertIn("speech", r["type"])
        self.assertEqual(r["speech"]["language"], "pl-PL")
        self.assertEqual(r["eventUrl"][0], "https://example.com/asr")

    def test_input_speech_end_on_silence(self):
        r = NccoBuilder.input_speech("https://x.com/asr", end_on_silence=3)
        self.assertEqual(r["speech"]["endOnSilence"], 3)

    def test_hangup_action(self):
        self.assertEqual(NccoBuilder.hangup()["action"], "hangup")

    def test_record_action(self):
        r = NccoBuilder.record("https://x.com/event")
        self.assertEqual(r["action"], "record")
        self.assertEqual(r["eventUrl"][0], "https://x.com/event")

    def test_opening_ncco_with_record(self):
        ncco = NccoBuilder.opening_ncco("RODO", "Pytanie?", "https://x.com/asr", "https://x.com/ev")
        actions = [n["action"] for n in ncco]
        self.assertEqual(actions, ["record", "talk", "talk", "input"])

    def test_opening_ncco_without_record(self):
        ncco = NccoBuilder.opening_ncco("RODO", "Pytanie?", "https://x.com/asr")
        actions = [n["action"] for n in ncco]
        self.assertEqual(actions, ["talk", "talk", "input"])

    def test_question_ncco(self):
        ncco = NccoBuilder.question_ncco("Do kiedy?", "https://x.com/asr")
        self.assertEqual(len(ncco), 2)
        self.assertEqual(ncco[0]["action"], "talk")
        self.assertEqual(ncco[1]["action"], "input")

    def test_closing_ncco(self):
        ncco = NccoBuilder.closing_ncco("Do widzenia!")
        self.assertEqual(len(ncco), 2)
        self.assertEqual(ncco[0]["text"], "Do widzenia!")
        self.assertEqual(ncco[1]["action"], "hangup")

    def test_ncco_json_serializable(self):
        ncco = NccoBuilder.opening_ncco("RODO", "Pytanie?", "https://x.com/asr")
        serialized = json.dumps(ncco)
        self.assertIsInstance(serialized, str)
        parsed = json.loads(serialized)
        self.assertEqual(len(parsed), 3)


# ------------------------------------------------------------------
# Testy logiki webhook przez helpery
# ------------------------------------------------------------------

SCENARIO_DATA = {
    "opening": "Czy dostarczyłeś dokumenty?",
    "nodes": {
        "q1": {
            "keywords_yes": ["tak"],
            "keywords_no": ["nie"],
            "keywords_optout": ["nie dzwoń"],
            "on_yes": {"say": "Dziękuję!", "action": "end", "extract": {"result": "TAK"}},
            "on_no": {"say": "Do kiedy?", "action": "goto", "next": "q2"},
        }
    },
    "closing_optout": "Rozumiem, do widzenia.",
    "closing_error": "Skontaktuje się pracownik biura.",
}


def _session(opt_out=False, extracted=None, attempt=1):
    return {
        "client_id": "KLIENT-001",
        "scenario_id": "Dokumenty",
        "scenario_data": SCENARIO_DATA,
        "rodo_message": "Tu system Abacus.",
        "current_node": "q1",
        "history": [],
        "digression_used": False,
        "context_data": {},
        "attempt": attempt,
        "opt_out": opt_out,
        "extracted_data": extracted or {},
    }


def _settings():
    s = MagicMock()
    s.webhook_base_url = "https://example.com/api/method/abacus_voice.webhook"
    s.get_password.return_value = "test-secret"
    s.optout_task_assignee = "admin@example.com"
    return s


class TestBuildNccoFromResult(unittest.TestCase):
    """Testuje _build_ncco_from_result przez import modułu."""

    def setUp(self):
        import abacus_voice.webhook as wh
        self.wh = wh
        self.settings = _settings()

    def test_action_end_returns_closing(self):
        from abacus_voice.engine.scenario_engine import DecisionResult, ACTION_END
        result = DecisionResult(action=ACTION_END, say_text="Dziękuję!")
        ncco = self.wh._build_ncco_from_result(result, self.settings)
        actions = [n["action"] for n in ncco]
        self.assertIn("hangup", actions)

    def test_action_goto_returns_question(self):
        from abacus_voice.engine.scenario_engine import DecisionResult, ACTION_GOTO
        result = DecisionResult(action=ACTION_GOTO, say_text="Do kiedy?", next_node="q2")
        ncco = self.wh._build_ncco_from_result(result, self.settings)
        actions = [n["action"] for n in ncco]
        self.assertIn("input", actions)
        self.assertNotIn("hangup", actions)

    def test_action_optout_returns_closing(self):
        from abacus_voice.engine.scenario_engine import DecisionResult, ACTION_OPTOUT
        result = DecisionResult(action=ACTION_OPTOUT, say_text="Rozumiem, do widzenia.")
        ncco = self.wh._build_ncco_from_result(result, self.settings)
        actions = [n["action"] for n in ncco]
        self.assertIn("hangup", actions)

    def test_action_unclear_returns_closing(self):
        from abacus_voice.engine.scenario_engine import DecisionResult, ACTION_UNCLEAR
        result = DecisionResult(action=ACTION_UNCLEAR, say_text="Przepraszam.")
        ncco = self.wh._build_ncco_from_result(result, self.settings)
        actions = [n["action"] for n in ncco]
        self.assertIn("hangup", actions)

    def test_action_digression_returns_question(self):
        from abacus_voice.engine.scenario_engine import DecisionResult, ACTION_DIGRESSION
        result = DecisionResult(action=ACTION_DIGRESSION, say_text="PIT w marcu. Czy dokumenty?")
        ncco = self.wh._build_ncco_from_result(result, self.settings)
        actions = [n["action"] for n in ncco]
        self.assertIn("input", actions)


class TestHandleCompleted(unittest.TestCase):

    @patch("abacus_voice.webhook.frappe")
    @patch("abacus_voice.webhook._save_call_log")
    @patch("abacus_voice.webhook._cancel_pending_queue")
    def test_completed_calls_save_log(self, mock_cancel, mock_save, mock_frappe):
        import abacus_voice.webhook as wh
        session = _session(extracted={"result": "TAK"})
        wh._handle_completed({"conversation_uuid": "CON-1", "recording_url": "https://r.url"}, session)
        mock_save.assert_called_once()
        call_kwargs = mock_save.call_args[1]
        self.assertEqual(call_kwargs["status"], "completed")
        self.assertEqual(call_kwargs["recording_url"], "https://r.url")

    @patch("abacus_voice.webhook.frappe")
    @patch("abacus_voice.webhook._save_call_log")
    @patch("abacus_voice.webhook._process_optout")
    @patch("abacus_voice.webhook._cancel_pending_queue")
    def test_completed_with_optout_calls_process_optout(self, mock_cancel, mock_optout, mock_save, mock_frappe):
        import abacus_voice.webhook as wh
        session = _session(opt_out=True)
        wh._handle_completed({"conversation_uuid": "CON-1"}, session)
        mock_optout.assert_called_once_with(session)

    @patch("abacus_voice.webhook.frappe")
    @patch("abacus_voice.webhook._save_call_log")
    @patch("abacus_voice.webhook._cancel_pending_queue")
    def test_completed_without_optout_does_not_call_process_optout(self, mock_cancel, mock_save, mock_frappe):
        import abacus_voice.webhook as wh
        with patch("abacus_voice.webhook._process_optout") as mock_optout:
            session = _session(opt_out=False, extracted={"result": "TAK"})
            wh._handle_completed({"conversation_uuid": "CON-1"}, session)
            mock_optout.assert_not_called()


class TestHandleUnanswered(unittest.TestCase):

    @patch("abacus_voice.webhook.frappe")
    def test_creates_queue_for_retry(self, mock_frappe):
        """Gdy attempt < max_retries → tworzy CallQueue."""
        import abacus_voice.webhook as wh

        mock_frappe.get_doc.side_effect = lambda doctype, name=None: (
            MagicMock(max_retries=3, retry_interval_hours=2)
            if doctype == "Call Scenario"
            else MagicMock()
        )
        mock_frappe.utils.add_to_date.return_value = "2026-05-26 12:00:00"
        mock_frappe.utils.now_datetime.return_value = "2026-05-26 10:00:00"
        mock_frappe.db.commit = MagicMock()

        session = _session(attempt=1)  # attempt=1 < max_retries=3
        wh._handle_unanswered({"conversation_uuid": "CON-1"}, session)

        # get_doc dla CallQueue insert powinien być wywołany
        calls = [str(c) for c in mock_frappe.get_doc.call_args_list]
        self.assertTrue(any("Call Queue" in c for c in calls))

    @patch("abacus_voice.webhook.frappe")
    @patch("abacus_voice.webhook._save_call_log")
    @patch("abacus_voice.webhook._escalate_to_office")
    def test_exhausted_escalates_to_office(self, mock_escalate, mock_save, mock_frappe):
        """Gdy attempt >= max_retries → eskalacja."""
        import abacus_voice.webhook as wh

        mock_frappe.get_doc.return_value = MagicMock(max_retries=3, retry_interval_hours=2)

        session = _session(attempt=3)  # attempt=3 == max_retries=3
        wh._handle_unanswered({"conversation_uuid": "CON-1"}, session)

        mock_escalate.assert_called_once()


class TestSaveCallLog(unittest.TestCase):

    @patch("abacus_voice.webhook.frappe")
    def test_save_creates_call_log_doc(self, mock_frappe):
        import abacus_voice.webhook as wh

        mock_doc = MagicMock()
        mock_frappe.get_doc.return_value = mock_doc
        mock_frappe.utils.now_datetime.return_value = "2026-05-25 12:00:00"
        mock_frappe.db.commit = MagicMock()

        session = _session()
        session["history"] = [
            {"speaker": "system", "text": "Tu system Abacus."},
            {"speaker": "client", "text": "tak"},
        ]
        wh._save_call_log(session, "completed", "https://rec.url", "CON-123")

        mock_frappe.get_doc.assert_called_once()
        doc_data = mock_frappe.get_doc.call_args[0][0]
        self.assertEqual(doc_data["doctype"], "Call Log")
        self.assertEqual(doc_data["status"], "completed")
        self.assertEqual(doc_data["recording_url"], "https://rec.url")
        self.assertIn("System: Tu system Abacus.", doc_data["transcript"])
        self.assertIn("Klient: tak", doc_data["transcript"])
        mock_doc.insert.assert_called_once()


class TestProcessOptout(unittest.TestCase):

    @patch("abacus_voice.webhook.frappe")
    @patch("abacus_voice.webhook._get_settings")
    def test_sets_opt_out_flag_on_customer(self, mock_settings, mock_frappe):
        import abacus_voice.webhook as wh
        mock_settings.return_value = _settings()
        mock_doc = MagicMock()
        mock_frappe.get_doc.return_value = mock_doc
        mock_frappe.db.commit = MagicMock()

        session = _session(opt_out=True)
        wh._process_optout(session)

        mock_frappe.db.set_value.assert_called_once_with(
            "Customer", "KLIENT-001", "voice_opt_out", 1
        )

    @patch("abacus_voice.webhook.frappe")
    @patch("abacus_voice.webhook._get_settings")
    def test_creates_task_for_support(self, mock_settings, mock_frappe):
        import abacus_voice.webhook as wh
        mock_settings.return_value = _settings()
        mock_doc = MagicMock()
        mock_frappe.get_doc.return_value = mock_doc
        mock_frappe.db.commit = MagicMock()

        session = _session(opt_out=True)
        wh._process_optout(session)

        mock_frappe.get_doc.assert_called_once()
        doc_data = mock_frappe.get_doc.call_args[0][0]
        self.assertEqual(doc_data["doctype"], "Task")
        self.assertIn("Opt-out", doc_data["subject"])
        mock_doc.insert.assert_called_once()


if __name__ == "__main__":
    unittest.main()
