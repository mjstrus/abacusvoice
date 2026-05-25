"""
Scheduler jobs dla abacus_voice.

process_call_queue() — uruchamiany co 15 minut przez Frappe Scheduler.
Pobiera pending CallQueue rekordy których czas nadszedł i inicjuje połączenia.
"""
import frappe


def process_call_queue():
    """
    Przetwarza pending rekordy CallQueue — inicjuje retry połączeń.

    Limity:
    - Max 10 połączeń na run żeby nie zalewać Vonage
    - Pomija rekordy z status != pending lub scheduled_at w przyszłości
    - Przy błędzie jednego rekordu kontynuuje pozostałe (izolacja błędów)
    """
    now = frappe.utils.now_datetime()

    pending_items = frappe.get_all(
        "Call Queue",
        filters={
            "status": "pending",
            "scheduled_at": ["<=", now],
        },
        fields=["name", "client_id", "scenario", "context_data", "attempt_number"],
        order_by="scheduled_at asc",
        limit=10,
    )

    if not pending_items:
        return

    frappe.logger("abacus_voice").info(
        f"process_call_queue: znaleziono {len(pending_items)} pending rekordów"
    )

    for item in pending_items:
        try:
            _process_queue_item(item)
        except Exception as e:
            frappe.log_error(
                title=f"abacus_voice: błąd retry dla {item.client_id}",
                message=f"CallQueue: {item.name}\nBłąd: {e}",
            )
            # Nie przerywaj — kontynuuj pozostałe
            continue


def _process_queue_item(item: dict):
    """Przetwarza pojedynczy rekord CallQueue."""
    from abacus_voice.api import _initiate_call_logic

    # Oznacz jako in_progress żeby uniknąć podwójnego wywołania
    frappe.db.set_value("Call Queue", item.name, "status", "in_progress")
    frappe.db.commit()

    try:
        _initiate_call_logic(
            client_id=item.client_id,
            scenario_id=item.scenario,
            context_data=item.context_data or None,
        )
        # Sukces — oznacz jako completed (CallLog zarządza dalej przez webhook)
        frappe.db.set_value("Call Queue", item.name, "status", "completed")
        frappe.db.commit()

    except Exception as e:
        # Przywróć status pending jeśli initiate_call się nie powiodło
        frappe.db.set_value("Call Queue", item.name, "status", "pending")
        frappe.db.commit()
        raise


@frappe.whitelist()
def cancel_queue_item(queue_name: str) -> dict:
    """
    Anulowanie zaplanowanego retry przez pracownika biura.
    Wywoływane z CallQueue list view (przycisk "Anuluj").

    Args:
        queue_name: Nazwa rekordu Call Queue.

    Returns:
        {"status": "cancelled", "name": queue_name}
    """
    doc = frappe.get_doc("Call Queue", queue_name)

    if doc.status != "pending":
        frappe.throw(
            f"Nie można anulować kolejki o statusie '{doc.status}'. "
            f"Można anulować tylko rekordy ze statusem 'pending'."
        )

    doc.status = "cancelled"
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {"status": "cancelled", "name": queue_name}
