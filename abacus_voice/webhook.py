"""
Vonage webhook handlers dla abacus_voice.

Trzy endpointy wywoływane przez Vonage Voice API:
- voice_answer  — Vonage pyta co robić gdy klient odbierze (answer_url)
- voice_asr     — Vonage przekazuje transkrypcję odpowiedzi klienta
- voice_event   — Vonage informuje o zmianie statusu połączenia

Wszystkie są Frappe whitelisted methods z allow_guest=True.
"""
import json
import frappe

from abacus_voice.engine.scenario_engine import (
    ScenarioEngine,
    ACTION_END, ACTION_GOTO, ACTION_OPTOUT, ACTION_UNCLEAR, ACTION_DIGRESSION,
)
from abacus_voice.engine.session import SessionManager
from abacus_voice.ncco_builder import NccoBuilder


# ------------------------------------------------------------------
# JWT verification
# ------------------------------------------------------------------

def _verify_vonage_jwt() -> bool:
    """
    Weryfikuje JWT Bearer token z nagłówka Authorization.
    Token jest HMAC-SHA256 podpisany vonage_signature_secret.
    Zwraca True jeśli prawidłowy, False jeśli nie.
    """
    try:
        from vonage_jwt.verify_jwt import verify_signature
    except ImportError:
        frappe.log_error(
            title="abacus_voice: brak vonage-jwt",
            message="Zainstaluj: pip install vonage-jwt"
        )
        return True  # nie blokuj w trybie dev bez biblioteki

    auth_header = frappe.request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return False

    token = auth_header[len("Bearer "):]
    settings = frappe.get_single("Voice Settings")
    signature_secret = settings.get_password("vonage_signature_secret")

    if not signature_secret:
        frappe.log_error(
            title="abacus_voice: brak vonage_signature_secret",
            message="Skonfiguruj Vonage Signature Secret w Voice Settings."
        )
        return False

    try:
        return bool(verify_signature(token, signature_secret))
    except Exception as e:
        frappe.log_error(title="abacus_voice: błąd JWT", message=str(e))
        return False


def _unauthorized():
    frappe.response["http_status_code"] = 403
    frappe.response["message"] = "Unauthorized"


def _get_settings():
    return frappe.get_single("Voice Settings")


def _asr_url(settings) -> str:
    return f"{settings.webhook_base_url}/voice_asr"


def _record_event_url(settings) -> str:
    return f"{settings.webhook_base_url}/voice_event"


# ------------------------------------------------------------------
# Endpoint 1: voice_answer
# ------------------------------------------------------------------

@frappe.whitelist(allow_guest=True)
def voice_answer():
    """
    Vonage answer_url — klient odbierze telefon.
    Zwraca NCCO: record + rodo + pierwsze pytanie + input_speech.
    """
    if not _verify_vonage_jwt():
        return _unauthorized()

    params = frappe.request.args
    conversation_uuid = params.get("conversation_uuid") or params.get("uuid")

    if not conversation_uuid:
        frappe.response["http_status_code"] = 400
        frappe.response["message"] = "Missing conversation_uuid"
        return

    session = SessionManager.get(conversation_uuid)
    if not session:
        frappe.log_error(
            title="abacus_voice: brak sesji w voice_answer",
            message=f"conversation_uuid={conversation_uuid}"
        )
        frappe.response["http_status_code"] = 404
        frappe.response["message"] = "Session not found"
        return

    settings = _get_settings()
    scenario_data = session.get("scenario_data", {})
    rodo_message = session.get("rodo_message", "Tu automatyczny system biura Abacus.")
    opening_text = scenario_data.get("opening", "")

    ncco = NccoBuilder.opening_ncco(
        rodo_text=rodo_message,
        opening_text=opening_text,
        asr_event_url=_asr_url(settings),
        record_event_url=_record_event_url(settings),
    )

    session = SessionManager.add_history(session, "system", rodo_message)
    session = SessionManager.add_history(session, "system", opening_text)
    SessionManager.update(conversation_uuid, session)

    frappe.response["content_type"] = "application/json"
    return ncco


# ------------------------------------------------------------------
# Endpoint 2: voice_asr
# ------------------------------------------------------------------

@frappe.whitelist(allow_guest=True)
def voice_asr():
    """
    Vonage ASR eventUrl — transkrypcja odpowiedzi klienta.
    Zwraca NCCO z następnym krokiem rozmowy.
    """
    if not _verify_vonage_jwt():
        return _unauthorized()

    try:
        data = json.loads(frappe.request.data or "{}")
    except json.JSONDecodeError:
        data = frappe.form_dict or {}

    conversation_uuid = data.get("conversation_uuid")
    if not conversation_uuid:
        frappe.response["http_status_code"] = 400
        return

    session = SessionManager.get(conversation_uuid)
    if not session:
        frappe.log_error(
            title="abacus_voice: brak sesji w voice_asr",
            message=f"conversation_uuid={conversation_uuid}"
        )
        settings = _get_settings()
        return NccoBuilder.closing_ncco(
            "Przepraszam, wystąpił błąd techniczny. Skontaktuje się z Tobą pracownik biura."
        )

    # Wyciągnij transkrypcję STT
    speech_results = data.get("speech", {}).get("results", [])
    if speech_results:
        speech_text = speech_results[0].get("text", "")
        confidence = float(speech_results[0].get("confidence", 0))
    else:
        speech_text = ""
        confidence = 0.0

    # Niska pewność → traktuj jak brak transkrypcji
    if confidence < 0.4:
        speech_text = ""

    settings = _get_settings()
    scenario_data = session.get("scenario_data", {})
    engine = ScenarioEngine(scenario_data)

    if not speech_text.strip():
        # Brak transkrypcji — powtórz pytanie
        current_node = session.get("current_node")
        question = engine._get_node_question(current_node) or scenario_data.get("opening", "")
        frappe.response["content_type"] = "application/json"
        return NccoBuilder.question_ncco(
            f"Przepraszam, nie usłyszałem. {question}",
            _asr_url(settings),
        )

    result, updated_session = engine.process_response(speech_text, session)
    SessionManager.update(conversation_uuid, updated_session)

    ncco = _build_ncco_from_result(result, settings)
    frappe.response["content_type"] = "application/json"
    return ncco


def _build_ncco_from_result(result, settings) -> list[dict]:
    """Tłumaczy DecisionResult na NCCO."""
    say_text = result.say_text or "Dziękuję."
    if result.action in (ACTION_END, ACTION_OPTOUT, ACTION_UNCLEAR):
        return NccoBuilder.closing_ncco(say_text)
    elif result.action in (ACTION_GOTO, ACTION_DIGRESSION):
        return NccoBuilder.question_ncco(say_text, _asr_url(settings))
    return NccoBuilder.closing_ncco(say_text)


# ------------------------------------------------------------------
# Endpoint 3: voice_event
# ------------------------------------------------------------------

@frappe.whitelist(allow_guest=True)
def voice_event():
    """
    Vonage event_url — statusy połączenia.
    Dla completed: zapisz CallLog.
    Dla unanswered/failed: utwórz CallQueue retry.
    """
    try:
        data = json.loads(frappe.request.data or "{}")
    except json.JSONDecodeError:
        data = frappe.form_dict or {}

    status = data.get("status", "")
    conversation_uuid = data.get("conversation_uuid", "")

    TERMINAL_STATUSES = {"completed", "unanswered", "rejected", "failed", "busy", "timeout"}
    if status not in TERMINAL_STATUSES:
        frappe.response["http_status_code"] = 200
        return {"status": "acknowledged"}

    session = SessionManager.get(conversation_uuid) if conversation_uuid else None

    if status == "completed" and session:
        _handle_completed(data, session)
    elif status in ("unanswered", "rejected", "failed", "busy", "timeout") and session:
        _handle_unanswered(data, session)

    if conversation_uuid and session:
        SessionManager.delete(conversation_uuid)

    frappe.response["http_status_code"] = 200
    return {"status": "ok"}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _handle_completed(data: dict, session: dict):
    _save_call_log(
        session=session,
        status="completed",
        recording_url=data.get("recording_url", ""),
        conversation_uuid=data.get("conversation_uuid", ""),
    )
    if session.get("opt_out"):
        _process_optout(session)
    extracted = session.get("extracted_data", {})
    if extracted.get("result") in ("TAK", "NIE"):
        _cancel_pending_queue(session)


def _handle_unanswered(data: dict, session: dict):

    client_id = session.get("client_id")
    scenario_id = session.get("scenario_id")
    attempt = session.get("attempt", 1)
    context_data = session.get("context_data", {})

    _save_call_log(
        session=session,
        status="unanswered",
        recording_url="",
        conversation_uuid=data.get("conversation_uuid", ""),
    )

    try:
        scenario = frappe.get_doc("Call Scenario", scenario_id)
        max_retries = scenario.max_retries or 3
        retry_hours = scenario.retry_interval_hours or 2
    except Exception:
        max_retries = 3
        retry_hours = 2

    if attempt >= max_retries:
        _escalate_to_office(client_id, scenario_id, attempt, context_data)
        return

    next_attempt_time = frappe.utils.add_to_date(
        frappe.utils.now_datetime(),
        hours=retry_hours,
    )

    queue_doc = frappe.get_doc({
        "doctype": "Call Queue",
        "client_id": client_id,
        "scenario": scenario_id,
        "status": "pending",
        "attempt_number": attempt + 1,
        "scheduled_at": next_attempt_time,
        "context_data": json.dumps(context_data, ensure_ascii=False) if context_data else "",
    })
    queue_doc.insert(ignore_permissions=True)
    frappe.db.commit()


def _save_call_log(session: dict, status: str, recording_url: str, conversation_uuid: str):

    history = session.get("history", [])
    transcript = "\n".join(
        f"{'System' if t['speaker'] == 'system' else 'Klient'}: {t['text']}"
        for t in history
    )
    extracted_data = session.get("extracted_data", {})

    log_doc = frappe.get_doc({
        "doctype": "Call Log",
        "client_id": session.get("client_id"),
        "scenario": session.get("scenario_id"),
        "conversation_uuid": conversation_uuid,
        "status": status,
        "attempt_number": session.get("attempt", 1),
        "transcript": transcript,
        "extracted_data": json.dumps(extracted_data, ensure_ascii=False) if extracted_data else "",
        "recording_url": recording_url,
        "ended_at": frappe.utils.now_datetime(),
    })
    log_doc.insert(ignore_permissions=True)
    frappe.db.commit()


def _process_optout(session: dict):
    client_id = session.get("client_id")
    if not client_id:
        return

    frappe.db.set_value("Customer", client_id, "voice_opt_out", 1)

    settings = _get_settings()
    assignee = settings.optout_task_assignee or "Administrator"

    frappe.get_doc({
        "doctype": "Task",
        "subject": f"Opt-out: {client_id} — prośba o zaprzestanie kontaktu automatycznego",
        "description": (
            f"Klient {client_id} podczas rozmowy automatycznej poprosił o wypisanie.\n\n"
            f"Skontaktuj się z klientem bezpośrednio. Aby odblokować automatyczny kontakt, "
            f"odznacz pole 'Wypisany z kontaktu automatycznego' w karcie klienta."
        ),
        "assigned_to": assignee,
        "status": "Open",
        "priority": "Medium",
    }).insert(ignore_permissions=True)
    frappe.db.commit()


def _cancel_pending_queue(session: dict):
    client_id = session.get("client_id")
    scenario_id = session.get("scenario_id")
    if not client_id:
        return

    pending = frappe.get_all(
        "Call Queue",
        filters={"client_id": client_id, "scenario": scenario_id, "status": "pending"},
        pluck="name",
    )
    for name in pending:
        frappe.db.set_value("Call Queue", name, "status", "cancelled")
    if pending:
        frappe.db.commit()


def _escalate_to_office(client_id: str, scenario_id: str, attempts: int, context_data: dict):
    settings = _get_settings()
    assignee = settings.optout_task_assignee or "Administrator"

    frappe.get_doc({
        "doctype": "Task",
        "subject": f"Niedozwoniony: {client_id} — {scenario_id}",
        "description": (
            f"System nie mógł dodzwonić się do {client_id} po {attempts} próbach "
            f"(scenariusz: {scenario_id}).\n\n"
            f"Dane: {json.dumps(context_data, ensure_ascii=False)}\n\n"
            f"Skontaktuj się ręcznie."
        ),
        "assigned_to": assignee,
        "status": "Open",
        "priority": "High",
    }).insert(ignore_permissions=True)

    frappe.db.sql("""
        UPDATE `tabCall Queue`
        SET status = 'exhausted'
        WHERE client_id = %s AND scenario = %s AND status = 'pending'
    """, (client_id, scenario_id))
    frappe.db.commit()
