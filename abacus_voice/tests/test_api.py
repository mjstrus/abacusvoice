"""
Testy jednostkowe dla api.py — initiate_call i helpery.
Testujemy logikę wewnętrzną bezpośrednio, pomijając @frappe.whitelist.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import json
import unittest
from unittest.mock import patch, MagicMock


# ------------------------------------------------------------------
# Pomocnicze mocki
# ------------------------------------------------------------------

def _mock_customer(voice_opt_out=0, mobile_no="+48501234567"):
    c = MagicMock()
    c.get.side_effect = lambda field, default=None: {
        "voice_opt_out": voice_opt_out,
        "mobile_no": mobile_no,
        "phone": None,
        "customer_name": "Jan Kowalski",
    }.get(field, default)
    c.name = "KLIENT-001"
    return c


def _mock_scenario(is_active=1):
    s = MagicMock()
    s.is_active = is_active
    s.name = "Dokumenty"
    s.scenario_json = json.dumps({
        "opening": "Dzień dobry, {{ client_name }}. Czy dostarczyłeś dokumenty?",
        "nodes": {
            "q1": {
                "keywords_yes": ["tak"],
                "keywords_no": ["nie"],
                "keywords_optout": ["nie dzwoń"],
                "on_yes": {"say": "Dziękuję!", "action": "end", "extract": {"result": "TAK"}},
                "on_no": {"say": "Do kiedy?", "action": "goto", "next": "q2"},
            }
        },
        "closing_optout": "Rozumiem.",
        "closing_error": "Skontaktuje się pracownik biura.",
    }, ensure_ascii=False)
    s.rodo_message = "Tu automatyczny system biura Abacus."
    return s


def _mock_settings():
    s = MagicMock()
    s.vonage_application_id = "app-123"
    s.vonage_phone_number = "+48221234567"
    s.webhook_base_url = "https://example.com/api/method/abacus_voice.webhook"
    s.get_password.side_effect = lambda field: {
        "vonage_private_key": "-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----",
    }.get(field)
    return s


def _mock_vonage_client(conversation_uuid="CON-abc123"):
    client = MagicMock()
    response = MagicMock()
    response.conversation_uuid = conversation_uuid
    client.voice.create_call.return_value = response
    return client


# ------------------------------------------------------------------
# Testy helperów — pure logic, bez Frappe
# ------------------------------------------------------------------

class TestParseContextData(unittest.TestCase):

    def setUp(self):
        import abacus_voice.api as api
        self.api = api

    def test_none_returns_empty_dict(self):
        self.assertEqual(self.api._parse_context_data(None), {})

    def test_dict_returned_as_is(self):
        data = {"kwota": "1500"}
        self.assertEqual(self.api._parse_context_data(data), data)

    def test_json_string_parsed(self):
        result = self.api._parse_context_data('{"kwota": "1500"}')
        self.assertEqual(result["kwota"], "1500")

    @patch("abacus_voice.api.frappe")
    def test_invalid_json_throws(self, mock_frappe):
        mock_frappe.throw.side_effect = Exception("invalid json")
        with self.assertRaises(Exception):
            self.api._parse_context_data("{bad json")


class TestNormalizePhone(unittest.TestCase):

    def setUp(self):
        import abacus_voice.api as api
        self.api = api

    def test_strips_plus(self):
        self.assertEqual(self.api._normalize_phone("+48501234567"), "48501234567")

    def test_strips_spaces(self):
        self.assertEqual(self.api._normalize_phone("+48 501 234 567"), "48501234567")

    def test_strips_dashes(self):
        self.assertEqual(self.api._normalize_phone("+48-501-234-567"), "48501234567")

    def test_already_normalized(self):
        self.assertEqual(self.api._normalize_phone("48501234567"), "48501234567")

    @patch("abacus_voice.api.frappe")
    def test_empty_throws(self, mock_frappe):
        mock_frappe.throw.side_effect = Exception("no phone")
        with self.assertRaises(Exception):
            self.api._normalize_phone("")

    @patch("abacus_voice.api.frappe")
    def test_non_numeric_throws(self, mock_frappe):
        mock_frappe.throw.side_effect = Exception("invalid phone")
        with self.assertRaises(Exception):
            self.api._normalize_phone("+48abc123")


# ------------------------------------------------------------------
# Testy logiki initiate_call przez _run_logic helper
# ------------------------------------------------------------------

def _run_initiate_call(
    client_id="KLIENT-001",
    scenario_id="Dokumenty",
    context_data=None,
    customer=None,
    scenario=None,
    vonage_client=None,
    vonage_error=None,
):
    """
    Uruchamia wewnętrzną logikę initiate_call z pełnym zestawem mocków.
    Omija @frappe.whitelist przez import i wywołanie _initiate_call_logic().
    """
    import abacus_voice.api as api

    customer = customer or _mock_customer()
    scenario = scenario or _mock_scenario()
    settings = _mock_settings()
    vonage = vonage_client or _mock_vonage_client()

    if vonage_error:
        vonage.voice.create_call.side_effect = vonage_error

    with patch("abacus_voice.api.frappe") as mock_frappe, \
         patch("abacus_voice.api.SessionManager") as mock_sm, \
         patch("abacus_voice.api._get_vonage_client", return_value=vonage), \
         patch("abacus_voice.api._create_initial_call_log") as mock_log:

        mock_frappe.get_doc.side_effect = lambda dt, n=None: {
            "Customer": customer,
            "Call Scenario": scenario,
        }.get(dt, MagicMock())
        mock_frappe.get_single.return_value = settings
        mock_frappe.throw.side_effect = lambda msg, *a, **kw: (_ for _ in ()).throw(
            Exception(msg)
        )
        mock_frappe.ValidationError = Exception
        mock_frappe.log_error = MagicMock()
        mock_sm.build_initial.return_value = {
            "client_id": client_id, "scenario_id": scenario_id,
            "scenario_data": {}, "history": [], "digression_used": False,
            "context_data": {}, "attempt": 1, "opt_out": False, "extracted_data": {},
        }

        # Wywołaj logikę bezpośrednio — omijając dekorator
        result = api._initiate_call_logic(
            client_id=client_id,
            scenario_id=scenario_id,
            context_data=context_data,
            frappe=mock_frappe,
        )

    return result, mock_sm, vonage, mock_log, mock_frappe


class TestInitiateCallLogic(unittest.TestCase):

    def test_successful_returns_initiated_status(self):
        result, *_ = _run_initiate_call()
        self.assertEqual(result["status"], "initiated")
        self.assertEqual(result["conversation_uuid"], "CON-abc123")

    def test_creates_redis_session_with_conversation_uuid(self):
        _, mock_sm, _, _, _ = _run_initiate_call()
        mock_sm.create.assert_called_once()
        args = mock_sm.create.call_args[0]
        self.assertEqual(args[0], "CON-abc123")

    def test_invokes_vonage_create_call(self):
        _, _, mock_vonage, _, _ = _run_initiate_call()
        mock_vonage.voice.create_call.assert_called_once()

    def test_creates_initial_call_log(self):
        _, _, _, mock_log, _ = _run_initiate_call()
        mock_log.assert_called_once_with(
            client_id="KLIENT-001",
            scenario_id="Dokumenty",
            conversation_uuid="CON-abc123",
        )

    def test_client_name_added_to_context(self):
        _, mock_sm, _, _, _ = _run_initiate_call(context_data=None)
        build_args = mock_sm.build_initial.call_args[1]
        ctx = build_args["context_data"]
        self.assertIn("client_name", ctx)
        self.assertEqual(ctx["client_name"], "Jan Kowalski")

    def test_context_data_dict_merged(self):
        _, mock_sm, _, _, _ = _run_initiate_call(context_data={"kwota": "1500"})
        build_args = mock_sm.build_initial.call_args[1]
        ctx = build_args["context_data"]
        self.assertEqual(ctx["kwota"], "1500")
        self.assertIn("client_name", ctx)

    def test_context_data_json_string_accepted(self):
        result, *_ = _run_initiate_call(context_data='{"kwota": "999"}')
        self.assertEqual(result["status"], "initiated")

    def test_opt_out_customer_raises(self):
        opted_out = _mock_customer(voice_opt_out=1)
        with self.assertRaises(Exception) as ctx:
            _run_initiate_call(customer=opted_out)
        self.assertIn("wypisany", str(ctx.exception))

    def test_inactive_scenario_raises(self):
        inactive = _mock_scenario(is_active=0)
        with self.assertRaises(Exception) as ctx:
            _run_initiate_call(scenario=inactive)
        self.assertIn("nieaktywny", str(ctx.exception))

    def test_vonage_error_raises_friendly_message(self):
        with self.assertRaises(Exception) as ctx:
            _run_initiate_call(vonage_error=Exception("Vonage 401 Unauthorized"))
        self.assertIn("Vonage", str(ctx.exception))

    def test_phone_normalized_for_vonage(self):
        """Numer +48 501 234 567 → 48501234567 w CreateCallRequest."""
        customer = _mock_customer(mobile_no="+48 501 234 567")
        captured = {}

        mock_vonage = MagicMock()
        def capture(req):
            captured["number"] = req.to[0].number
            r = MagicMock()
            r.conversation_uuid = "CON-abc"
            return r
        mock_vonage.voice.create_call.side_effect = capture

        _run_initiate_call(customer=customer, vonage_client=mock_vonage)
        self.assertEqual(captured.get("number"), "48501234567")

    def test_rodo_message_stored_in_session(self):
        """rodo_message ze scenariusza trafia do sesji (voice_answer go użyje)."""
        _, mock_sm, _, _, _ = _run_initiate_call()
        create_args = mock_sm.create.call_args[0]
        session_data = create_args[1]
        self.assertIn("rodo_message", session_data)
        self.assertEqual(session_data["rodo_message"], "Tu automatyczny system biura Abacus.")

    def test_answer_url_contains_voice_answer(self):
        """answer_url w CreateCallRequest wskazuje na voice_answer webhook."""
        captured = {}
        mock_vonage = MagicMock()
        def capture(req):
            captured["answer_url"] = req.answer_url[0]
            r = MagicMock()
            r.conversation_uuid = "CON-abc"
            return r
        mock_vonage.voice.create_call.side_effect = capture

        _run_initiate_call(vonage_client=mock_vonage)
        self.assertIn("voice_answer", captured.get("answer_url", ""))


class TestCreateInitialCallLog(unittest.TestCase):

    @patch("abacus_voice.api.frappe")
    def test_creates_doc_with_initiated_status(self, mock_frappe):
        import abacus_voice.api as api

        mock_doc = MagicMock()
        mock_frappe.get_doc.return_value = mock_doc
        mock_frappe.db.commit = MagicMock()

        api._create_initial_call_log("KLIENT-001", "Dokumenty", "CON-xyz")

        doc_data = mock_frappe.get_doc.call_args[0][0]
        self.assertEqual(doc_data["doctype"], "Call Log")
        self.assertEqual(doc_data["status"], "initiated")
        self.assertEqual(doc_data["conversation_uuid"], "CON-xyz")
        mock_doc.insert.assert_called_once()


if __name__ == "__main__":
    unittest.main()
