import frappe
from frappe.model.document import Document


class CallLog(Document):

    def before_insert(self):
        if not self.started_at:
            self.started_at = frappe.utils.now_datetime()
