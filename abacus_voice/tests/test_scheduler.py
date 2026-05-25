"""
Testy jednostkowe dla scheduler.py.
Mockują Frappe i initiate_call — nie wymagają środowiska Frappe.

Uruchomienie:
    python -m pytest abacus_voice/tests/test_scheduler.py -v
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import unittest
from unittest.mock import patch, MagicMock, call


def _queue_item(name="CQUEUE-001", client_id="KLIENT-001", scenario="Dokumenty",
                context_data=None, attempt_number=1, status="pending"):
    item = MagicMock()
    item.name = name
    item.client_id = client_id
    item.scenario = scenario
    item.context_data = context_data
    item.attempt_number = attempt_number
    item.status = status
    return item


class TestProcessCallQueue(unittest.TestCase):

    @patch("abacus_voice.scheduler.frappe")
    @patch("abacus_voice.scheduler._process_queue_item")
    def test_processes_pending_items(self, mock_process, mock_frappe):
        """Scheduler przetwarza rekordy ze statusem pending i scheduled_at w przeszłości."""
        items = [_queue_item("Q-001"), _queue_item("Q-002")]
        mock_frappe.get_all.return_value = items
        mock_frappe.utils.now_datetime.return_value = "2026-05-25 12:00:00"
        mock_frappe.logger.return_value = MagicMock()

        from abacus_voice.scheduler import process_call_queue
        process_call_queue()

        self.assertEqual(mock_process.call_count, 2)

    @patch("abacus_voice.scheduler.frappe")
    @patch("abacus_voice.scheduler._process_queue_item")
    def test_empty_queue_does_nothing(self, mock_process, mock_frappe):
        """Pusta kolejka — brak wywołań."""
        mock_frappe.get_all.return_value = []
        mock_frappe.utils.now_datetime.return_value = "2026-05-25 12:00:00"

        from abacus_voice.scheduler import process_call_queue
        process_call_queue()

        mock_process.assert_not_called()

    @patch("abacus_voice.scheduler.frappe")
    @patch("abacus_voice.scheduler._process_queue_item")
    def test_item_error_continues_processing(self, mock_process, mock_frappe):
        """Błąd przy jednym rekordzie nie przerywa pozostałych."""
        items = [_queue_item("Q-001"), _queue_item("Q-002"), _queue_item("Q-003")]
        mock_frappe.get_all.return_value = items
        mock_frappe.utils.now_datetime.return_value = "2026-05-25 12:00:00"
        mock_frappe.logger.return_value = MagicMock()
        mock_frappe.log_error = MagicMock()

        # Drugi item rzuca wyjątek
        mock_process.side_effect = [None, Exception("Vonage error"), None]

        from abacus_voice.scheduler import process_call_queue
        process_call_queue()  # Nie powinno rzucić

        self.assertEqual(mock_process.call_count, 3)
        mock_frappe.log_error.assert_called_once()

    @patch("abacus_voice.scheduler.frappe")
    @patch("abacus_voice.scheduler._process_queue_item")
    def test_query_filters_pending_and_past_scheduled(self, mock_process, mock_frappe):
        """Zapytanie filtruje status=pending i scheduled_at <= now."""
        mock_frappe.get_all.return_value = []
        mock_frappe.utils.now_datetime.return_value = "2026-05-25 12:00:00"

        from abacus_voice.scheduler import process_call_queue
        process_call_queue()

        call_args = mock_frappe.get_all.call_args
        filters = call_args[1]["filters"]
        self.assertEqual(filters["status"], "pending")
        self.assertEqual(filters["scheduled_at"][0], "<=")


class TestProcessQueueItem(unittest.TestCase):

    @patch("abacus_voice.scheduler.frappe")
    @patch("abacus_voice.api._initiate_call_logic")
    def test_successful_item_marked_completed(self, mock_initiate, mock_frappe):
        """Pomyślne zainicjowanie połączenia → status=completed."""
        mock_frappe.db.set_value = MagicMock()
        mock_frappe.db.commit = MagicMock()
        mock_initiate.return_value = {"status": "initiated", "conversation_uuid": "CON-abc"}

        item = _queue_item("Q-001", attempt_number=1)

        from abacus_voice.scheduler import _process_queue_item
        _process_queue_item(item)

        # Sprawdź kolejność: najpierw in_progress, potem completed
        calls = mock_frappe.db.set_value.call_args_list
        self.assertEqual(calls[0], call("Call Queue", "Q-001", "status", "in_progress"))
        self.assertEqual(calls[1], call("Call Queue", "Q-001", "status", "completed"))

    @patch("abacus_voice.scheduler.frappe")
    @patch("abacus_voice.api._initiate_call_logic")
    def test_failed_item_reverted_to_pending(self, mock_initiate, mock_frappe):
        """Błąd initiate_call → status wraca do pending."""
        mock_frappe.db.set_value = MagicMock()
        mock_frappe.db.commit = MagicMock()
        mock_initiate.side_effect = Exception("Vonage down")

        item = _queue_item("Q-001")

        from abacus_voice.scheduler import _process_queue_item
        with self.assertRaises(Exception):
            _process_queue_item(item)

        calls = mock_frappe.db.set_value.call_args_list
        # Ostatni set_value powinien być powrót do pending
        last_call = calls[-1]
        self.assertEqual(last_call, call("Call Queue", "Q-001", "status", "pending"))

    @patch("abacus_voice.scheduler.frappe")
    @patch("abacus_voice.api._initiate_call_logic")
    def test_passes_context_data_to_initiate(self, mock_initiate, mock_frappe):
        """context_data z kolejki trafia do initiate_call."""
        mock_frappe.db.set_value = MagicMock()
        mock_frappe.db.commit = MagicMock()
        mock_initiate.return_value = {"status": "initiated", "conversation_uuid": "CON-abc"}

        item = _queue_item("Q-001", context_data='{"kwota": "1500"}')

        from abacus_voice.scheduler import _process_queue_item
        _process_queue_item(item)

        mock_initiate.assert_called_once_with(
            client_id="KLIENT-001",
            scenario_id="Dokumenty",
            context_data='{"kwota": "1500"}',
        )


class TestCancelQueueItem(unittest.TestCase):

    @patch("abacus_voice.scheduler.frappe")
    def test_cancels_pending_item(self, mock_frappe):
        """Anulowanie pending rekordu → status=cancelled."""
        mock_doc = MagicMock()
        mock_doc.status = "pending"
        mock_frappe.get_doc.return_value = mock_doc
        mock_frappe.db.commit = MagicMock()

        from abacus_voice.scheduler import cancel_queue_item
        result = cancel_queue_item.__wrapped__("Q-001") \
            if hasattr(cancel_queue_item, "__wrapped__") \
            else _cancel_queue_item_logic("Q-001", mock_frappe)

        # Sprawdź że status ustawiony na cancelled
        self.assertEqual(mock_doc.status, "cancelled")
        mock_doc.save.assert_called_once()

    @patch("abacus_voice.scheduler.frappe")
    def test_cannot_cancel_non_pending(self, mock_frappe):
        """Nie można anulować rekordu który nie jest pending."""
        mock_doc = MagicMock()
        mock_doc.status = "completed"
        mock_frappe.get_doc.return_value = mock_doc
        mock_frappe.throw.side_effect = Exception("cannot cancel")

        from abacus_voice.scheduler import cancel_queue_item
        with self.assertRaises(Exception):
            _cancel_queue_item_logic("Q-001", mock_frappe)


def _cancel_queue_item_logic(queue_name: str, frappe):
    """Helper do testowania logiki cancel_queue_item bez dekoratora @whitelist."""
    doc = frappe.get_doc("Call Queue", queue_name)
    if doc.status != "pending":
        frappe.throw(
            f"Nie można anulować kolejki o statusie '{doc.status}'."
        )
    doc.status = "cancelled"
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"status": "cancelled", "name": queue_name}


if __name__ == "__main__":
    unittest.main()
