"""
SessionManager — zarządzanie stanem aktywnej rozmowy w Redis.

Klucz: abacus_voice:session:{conversation_uuid}
TTL:   1800s (30 minut)

Struktura sesji:
{
    "scenario_id":      str,      # nazwa CallScenario
    "scenario_data":    dict,     # sparsowany JSON scenariusza (po Jinja2 render)
    "current_node":     str,      # ID bieżącego węzła, np. "q1"
    "history":          list,     # lista tur: [{speaker, text}, ...]
    "digression_used":  bool,     # czy klient już wykorzystał swoją dygresję
    "context_data":     dict,     # dane przekazane przy inicjowaniu (np. {kwota: "1500"})
    "client_id":        str,      # nazwa Customer w Frappe
    "attempt":          int,      # numer próby połączenia
    "opt_out":          bool,     # czy klient poprosił o opt-out podczas rozmowy
    "extracted_data":   dict,     # dane zebrane z rozmowy (np. {result: "NIE", deadline: "piątek"})
}
"""
import json
import frappe


REDIS_PREFIX = "abacus_voice:session:"
REDIS_TTL = 1800  # 30 minut


class SessionManager:

    @staticmethod
    def _key(conversation_uuid: str) -> str:
        return f"{REDIS_PREFIX}{conversation_uuid}"

    @staticmethod
    def create(conversation_uuid: str, session_data: dict) -> None:
        """Tworzy nową sesję w Redis z TTL 30 minut."""
        key = SessionManager._key(conversation_uuid)
        frappe.cache().set_value(
            key,
            json.dumps(session_data, ensure_ascii=False),
            expires_in_sec=REDIS_TTL,
        )

    @staticmethod
    def get(conversation_uuid: str) -> dict | None:
        """Pobiera sesję. Zwraca None jeśli nie istnieje lub wygasła."""
        key = SessionManager._key(conversation_uuid)
        raw = frappe.cache().get_value(key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    @staticmethod
    def update(conversation_uuid: str, session_data: dict) -> None:
        """Nadpisuje sesję — odświeża TTL."""
        SessionManager.create(conversation_uuid, session_data)

    @staticmethod
    def delete(conversation_uuid: str) -> None:
        """Usuwa sesję z Redis po zakończeniu rozmowy."""
        key = SessionManager._key(conversation_uuid)
        frappe.cache().delete_value(key)

    @staticmethod
    def add_history(session: dict, speaker: str, text: str) -> dict:
        """Dodaje turę do historii rozmowy. Zwraca zaktualizowaną sesję."""
        session.setdefault("history", [])
        session["history"].append({"speaker": speaker, "text": text})
        return session

    @staticmethod
    def build_initial(
        client_id: str,
        scenario_id: str,
        scenario_data: dict,
        context_data: dict,
        attempt: int = 1,
    ) -> dict:
        """Buduje strukturę nowej sesji."""
        # Pierwszym węzłem jest zawsze klucz pierwszy w nodes
        first_node = next(iter(scenario_data.get("nodes", {})), None)
        return {
            "scenario_id": scenario_id,
            "scenario_data": scenario_data,
            "current_node": first_node,
            "history": [],
            "digression_used": False,
            "context_data": context_data or {},
            "client_id": client_id,
            "attempt": attempt,
            "opt_out": False,
            "extracted_data": {},
        }
