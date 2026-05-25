import frappe
from frappe.model.document import Document


class CallQueue(Document):

    def cancel_retry(self):
        """Anulowanie zaplanowanego retry przez pracownika biura."""
        if self.status != "pending":
            frappe.throw(f"Nie można anulować kolejki o statusie '{self.status}'.")
        self.status = "cancelled"
        self.save()
        frappe.msgprint(f"Retry dla klienta {self.client_id} anulowany.")
