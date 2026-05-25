"""
Publiczne API abacus_voice — initiate_call.

Wywoływane z:
- Frappe UI (Customer form → przycisk "Zadzwoń")
- Innych modułów Frappe (windykacja, generator pism) przez frappe.call()

Endpoint: frappe.call("abacus_voice.api.initiate_call", {...})
"""
import json
import uuid as uuid_module

import frappe

from abacus_voice.engine.scenario_engine import ScenarioEngine
from abacus_voice.engine.session import SessionManager


def _get_vonage_client(settings):
    """Buduje Vonage client z VoiceSettings."""
    from vonage import Vonage, Auth

    private_key = settings.get_password("vonage_private_key")
    if not private_key:
        frappe.throw("Vonage Private Key nie jest skonfigurowany w Voice Settings.")

    return Vonage(Auth(
        application_id=settings.vonage_application_id,
        private_key=private_key,
    ))


def _parse_context_data(context_data) -> dict:
    """Parsuje context_data — przyjmuje dict lub JSON string."""
    if context_data is None:
        return {}
    if isinstance(context_data, dict):
        return context_data
    if isinstance(context_data, str):
        try:
            return json.loads(context_data)
        except json.JSONDecodeError:
            frappe.throw(f"context_data musi być prawidłowym JSON. Otrzymano: {context_data[:100]}")
    return {}


def _normalize_phone(phone: str) -> str:
    """
    Normalizuje numer telefonu do formatu E.164 bez znaku '+'.
    Vonage oczekuje numerów bez '+' (np. '48501234567').
    """
    if not phone:
        frappe.throw("Klient nie ma przypisanego numeru telefonu.")
    phone = phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith("+"):
        phone = phone[1:]
    if not phone.isdigit():
        frappe.throw(f"Nieprawidłowy format numeru telefonu: {phone}")
    return phone


@frappe.whitelist()
def initiate_call(client_id: str, scenario_id: str, context_data=None) -> dict:
    """
    Inicjuje automatyczne połączenie telefoniczne do klienta.

    Args:
        client_id:    Nazwa dokumentu Customer w Frappe.
        scenario_id:  Nazwa dokumentu Call Scenario.
        context_data: Dict lub JSON string z danymi do Jinja2 render
                      (np. {"client_name": "Jan Kowalski", "kwota": "1500"}).

    Returns:
        {"status": "initiated", "conversation_uuid": "CON-xxx"}

    Raises:
        frappe.ValidationError: gdy klient ma opt_out, scenariusz jest nieaktywny,
                                 brak numeru telefonu, lub inne błędy walidacji.
    """
    # 1. Walidacja klienta
    customer = frappe.get_doc("Customer", client_id)

    if customer.get("voice_opt_out"):
        frappe.throw(
            f"Klient {client_id} jest wypisany z kontaktu automatycznego (voice_opt_out=True). "
            f"Odblokuj flagę w karcie klienta przed zainicjowaniem rozmowy.",
            frappe.ValidationError,
        )

    phone = _normalize_phone(
        customer.get("mobile_no") or customer.get("phone") or ""
    )

    # 2. Walidacja scenariusza
    scenario = frappe.get_doc("Call Scenario", scenario_id)

    if not scenario.is_active:
        frappe.throw(
            f"Scenariusz '{scenario_id}' jest nieaktywny. Aktywuj go w Call Scenario przed użyciem.",
            frappe.ValidationError,
        )

    # 3. Parsuj context_data i dodaj dane klienta jako domyślne zmienne
    ctx = _parse_context_data(context_data)
    ctx.setdefault("client_name", customer.get("customer_name") or client_id)
    ctx.setdefault("client_id", client_id)

    # 4. Jinja2 render scenariusza + buduj ScenarioEngine
    engine = ScenarioEngine.from_rendered_json(scenario.scenario_json, ctx)
    rendered_scenario_data = engine.scenario_data

    # 5. Utwórz wstępną sesję z tymczasowym UUID (prawdziwy conversation_uuid
    #    przyjdzie z Vonage po create_call)
    temp_uuid = f"pending-{uuid_module.uuid4().hex[:8]}"
    session = SessionManager.build_initial(
        client_id=client_id,
        scenario_id=scenario_id,
        scenario_data=rendered_scenario_data,
        context_data=ctx,
    )
    # Dodaj rodo_message do sesji (potrzebne w voice_answer)
    session["rodo_message"] = scenario.rodo_message

    # 6. Pobierz ustawienia i zainicjuj połączenie przez Vonage
    settings = frappe.get_single("Voice Settings")

    vonage_client = _get_vonage_client(settings)

    from vonage_voice.models import CreateCallRequest, ToPhone, Phone

    call_request = CreateCallRequest(
        to=[ToPhone(number=phone)],
        from_=Phone(number=_normalize_phone(settings.vonage_phone_number)),
        answer_url=[f"{settings.webhook_base_url}/voice_answer"],
        event_url=[f"{settings.webhook_base_url}/voice_event"],
        record=True,
    )

    try:
        response = vonage_client.voice.create_call(call_request)
    except Exception as e:
        frappe.log_error(
            title="abacus_voice: błąd Vonage create_call",
            message=f"client_id={client_id}, scenario={scenario_id}\n{e}",
        )
        frappe.throw(f"Nie udało się zainicjować połączenia przez Vonage: {e}")

    conversation_uuid = response.conversation_uuid

    # 7. Zapisz sesję w Redis pod prawdziwym conversation_uuid
    SessionManager.create(conversation_uuid, session)

    # 8. Utwórz wstępny CallLog ze statusem 'initiated'
    _create_initial_call_log(
        client_id=client_id,
        scenario_id=scenario_id,
        conversation_uuid=conversation_uuid,
    )

    return {
        "status": "initiated",
        "conversation_uuid": conversation_uuid,
    }


def _create_initial_call_log(client_id: str, scenario_id: str, conversation_uuid: str):
    """Tworzy wstępny CallLog z statusem 'initiated' — aktualizowany przez voice_event."""
    log_doc = frappe.get_doc({
        "doctype": "Call Log",
        "client_id": client_id,
        "scenario": scenario_id,
        "conversation_uuid": conversation_uuid,
        "status": "initiated",
        "attempt_number": 1,
    })
    log_doc.insert(ignore_permissions=True)
    frappe.db.commit()


def _initiate_call_logic(
    client_id: str,
    scenario_id: str,
    context_data=None,
    frappe=None,
) -> dict:
    """
    Wewnętrzna logika initiate_call — wydzielona dla testowalności.
    W produkcji wywoływana przez initiate_call() z prawdziwym frappe.
    W testach wywoływana bezpośrednio z mockowanym frappe.
    """
    if frappe is None:
        import frappe as _frappe
        frappe = _frappe

    # 1. Walidacja klienta
    customer = frappe.get_doc("Customer", client_id)
    if customer.get("voice_opt_out"):
        frappe.throw(
            f"Klient {client_id} jest wypisany z kontaktu automatycznego (voice_opt_out=True). "
            f"Odblokuj flagę w karcie klienta przed zainicjowaniem rozmowy.",
            frappe.ValidationError,
        )

    phone = _normalize_phone(
        customer.get("mobile_no") or customer.get("phone") or ""
    )

    # 2. Walidacja scenariusza
    scenario = frappe.get_doc("Call Scenario", scenario_id)
    if not scenario.is_active:
        frappe.throw(
            f"Scenariusz '{scenario_id}' jest nieaktywny. Aktywuj go w Call Scenario przed użyciem.",
            frappe.ValidationError,
        )

    # 3. Context data + defaults
    ctx = _parse_context_data(context_data)
    ctx.setdefault("client_name", customer.get("customer_name") or client_id)
    ctx.setdefault("client_id", client_id)

    # 4. Jinja2 render
    engine = ScenarioEngine.from_rendered_json(scenario.scenario_json, ctx)
    rendered_scenario_data = engine.scenario_data

    # 5. Wstępna sesja
    session = SessionManager.build_initial(
        client_id=client_id,
        scenario_id=scenario_id,
        scenario_data=rendered_scenario_data,
        context_data=ctx,
    )
    session["rodo_message"] = scenario.rodo_message

    # 6. Vonage
    settings = frappe.get_single("Voice Settings")
    vonage_client = _get_vonage_client(settings)

    from vonage_voice.models import CreateCallRequest, ToPhone, Phone

    call_request = CreateCallRequest(
        to=[ToPhone(number=phone)],
        from_=Phone(number=_normalize_phone(settings.vonage_phone_number)),
        answer_url=[f"{settings.webhook_base_url}/voice_answer"],
        event_url=[f"{settings.webhook_base_url}/voice_event"],
        record=True,
    )

    try:
        response = vonage_client.voice.create_call(call_request)
    except Exception as e:
        frappe.log_error(
            title="abacus_voice: błąd Vonage create_call",
            message=f"client_id={client_id}, scenario={scenario_id}\n{e}",
        )
        frappe.throw(f"Nie udało się zainicjować połączenia przez Vonage: {e}")

    conversation_uuid = response.conversation_uuid

    # 7. Zapisz sesję w Redis
    SessionManager.create(conversation_uuid, session)

    # 8. Wstępny CallLog
    _create_initial_call_log(
        client_id=client_id,
        scenario_id=scenario_id,
        conversation_uuid=conversation_uuid,
    )

    return {
        "status": "initiated",
        "conversation_uuid": conversation_uuid,
    }
