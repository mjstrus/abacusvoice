"""
Testy dla Unit 1: DocTypes aplikacji abacus_voice.

Uruchomienie:
    bench run-tests --app abacus_voice --module abacus_voice.tests.test_doctypes
"""
import json
import unittest
import frappe
from frappe.exceptions import ValidationError


class TestCallScenario(unittest.TestCase):

    def setUp(self):
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.db.rollback()

    def _make_valid_scenario(self, title="Test Scenariusz"):
        scenario_data = {
            "opening": "Dzień dobry, {{ client_name }}. Czy dostarczyłeś dokumenty?",
            "nodes": {
                "q1": {
                    "keywords_yes": ["tak", "już"],
                    "keywords_no": ["nie", "jeszcze"],
                    "keywords_optout": ["nie dzwoń"],
                    "on_yes": {"say": "Dziękuję!", "action": "end", "extract": {"result": "TAK"}},
                    "on_no": {"say": "Do kiedy?", "action": "goto", "next": "q2"},
                    "on_unclear": "claude_fallback"
                },
                "q2": {
                    "capture_as": "deadline",
                    "say_template": "Dziękuję, zanotowałem.",
                    "action": "end",
                    "extract": {"result": "NIE", "deadline": "{{captured}}"}
                }
            },
            "closing_optout": "Rozumiem, do widzenia.",
            "closing_error": "Skontaktuje się z Tobą pracownik biura."
        }
        return frappe.get_doc({
            "doctype": "Call Scenario",
            "title": title,
            "rodo_message": "Tu system Abacus. Czy mogę zadać pytanie?",
            "max_retries": 3,
            "retry_interval_hours": 2,
            "scenario_json": json.dumps(scenario_data, ensure_ascii=False)
        })

    def test_valid_scenario_saves_successfully(self):
        """Zapis scenariusza z prawidłowym JSON powinien się udać."""
        doc = self._make_valid_scenario()
        doc.insert()
        self.assertTrue(frappe.db.exists("Call Scenario", doc.name))

    def test_empty_scenario_json_raises_error(self):
        """Pusty scenario_json powinien rzucić ValidationError."""
        doc = self._make_valid_scenario("Test Pusty")
        doc.scenario_json = ""
        with self.assertRaises(ValidationError):
            doc.insert()

    def test_invalid_json_raises_error(self):
        """Nieprawidłowy JSON powinien rzucić ValidationError."""
        doc = self._make_valid_scenario("Test Zły JSON")
        doc.scenario_json = "{to nie jest json"
        with self.assertRaises(ValidationError):
            doc.insert()

    def test_missing_opening_raises_error(self):
        """Brak pola 'opening' w JSON powinien rzucić ValidationError."""
        doc = self._make_valid_scenario("Test Brak Opening")
        data = {"nodes": {"q1": {}}}
        doc.scenario_json = json.dumps(data)
        with self.assertRaises(ValidationError):
            doc.insert()

    def test_missing_nodes_raises_error(self):
        """Brak pola 'nodes' w JSON powinien rzucić ValidationError."""
        doc = self._make_valid_scenario("Test Brak Nodes")
        data = {"opening": "Cześć"}
        doc.scenario_json = json.dumps(data)
        with self.assertRaises(ValidationError):
            doc.insert()

    def test_empty_nodes_raises_error(self):
        """Pusty słownik 'nodes' powinien rzucić ValidationError."""
        doc = self._make_valid_scenario("Test Puste Nodes")
        data = {"opening": "Cześć", "nodes": {}}
        doc.scenario_json = json.dumps(data)
        with self.assertRaises(ValidationError):
            doc.insert()

    def test_inactive_scenario(self):
        """Scenariusz można dezaktywować."""
        doc = self._make_valid_scenario("Test Nieaktywny")
        doc.is_active = 0
        doc.insert()
        saved = frappe.get_doc("Call Scenario", doc.name)
        self.assertEqual(saved.is_active, 0)


class TestCallLog(unittest.TestCase):

    def setUp(self):
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.db.rollback()

    def test_call_log_auto_sets_started_at(self):
        """CallLog powinien automatycznie ustawić started_at przy insercie."""
        # Wymaga istniejącego klienta i scenariusza w bazie testowej.
        # W środowisku testowym Frappe można użyć frappe.get_test_records.
        pass  # placeholder — pełny test wymaga fixture danych


class TestCustomerOptOut(unittest.TestCase):

    def setUp(self):
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.db.rollback()

    def test_voice_opt_out_field_exists(self):
        """Pole voice_opt_out powinno istnieć w Customer DocType po bench migrate."""
        meta = frappe.get_meta("Customer")
        field_names = [f.fieldname for f in meta.fields]
        self.assertIn("voice_opt_out", field_names)

    def test_voice_opt_out_default_is_zero(self):
        """Domyślna wartość voice_opt_out powinna być 0 (nie wypisany)."""
        meta = frappe.get_meta("Customer")
        field = meta.get_field("voice_opt_out")
        self.assertIsNotNone(field)
        self.assertEqual(field.default, "0")


class TestVoiceSettings(unittest.TestCase):

    def setUp(self):
        frappe.set_user("Administrator")

    def test_voice_settings_is_single(self):
        """VoiceSettings powinien być Single DocType."""
        meta = frappe.get_meta("Voice Settings")
        self.assertTrue(meta.issingle)

    def test_get_settings_helper(self):
        """Metoda get_settings() powinna zwracać dokument Voice Settings."""
        from abacus_voice.doctype.voice_settings.voice_settings import VoiceSettings
        settings = VoiceSettings.get_settings()
        self.assertEqual(settings.doctype, "Voice Settings")


if __name__ == "__main__":
    unittest.main()
