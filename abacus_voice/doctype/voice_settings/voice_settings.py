import frappe
from frappe.model.document import Document


class VoiceSettings(Document):

    @staticmethod
    def get_settings():
        """Skrót do pobierania ustawień — używany w całej aplikacji."""
        return frappe.get_single("Voice Settings")
