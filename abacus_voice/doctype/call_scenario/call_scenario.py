import json
import frappe
from frappe.model.document import Document


class CallScenario(Document):

    def validate(self):
        self._validate_scenario_json()

    def _validate_scenario_json(self):
        if not self.scenario_json or not self.scenario_json.strip():
            frappe.throw("Scenariusz (JSON) nie może być pusty.")

        try:
            data = json.loads(self.scenario_json)
        except json.JSONDecodeError as e:
            frappe.throw(f"Scenariusz zawiera nieprawidłowy JSON: {e}")

        # Wymagane klucze na poziomie głównym
        if "opening" not in data:
            frappe.throw("Scenariusz musi zawierać pole 'opening'.")
        if "nodes" not in data or not isinstance(data["nodes"], dict):
            frappe.throw("Scenariusz musi zawierać pole 'nodes' (słownik węzłów).")
        if not data["nodes"]:
            frappe.throw("Scenariusz musi zawierać przynajmniej jeden węzeł w 'nodes'.")
