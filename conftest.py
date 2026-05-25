"""
conftest.py — mockuje moduł `frappe` dla testów uruchamianych poza środowiskiem Frappe.

W środowisku Frappe (bench run-tests) ten plik jest ignorowany bo frappe jest dostępne.
Poza nim (lokalny pytest, CI) podmienia frappe na MagicMock.
"""
import sys
from unittest.mock import MagicMock

# Podmień `frappe` zanim jakikolwiek moduł go zaimportuje
if "frappe" not in sys.modules:
    mock_frappe = MagicMock()

    # Najczęściej używane atrybuty które muszą działać deterministycznie
    mock_frappe.throw = lambda msg, *a, **kw: (_ for _ in ()).throw(Exception(msg))
    mock_frappe.log_error = MagicMock()
    mock_frappe.get_single = MagicMock()
    mock_frappe.cache = MagicMock()

    sys.modules["frappe"] = mock_frappe
    sys.modules["frappe.model"] = MagicMock()
    sys.modules["frappe.model.document"] = MagicMock()
    sys.modules["frappe.exceptions"] = MagicMock()
