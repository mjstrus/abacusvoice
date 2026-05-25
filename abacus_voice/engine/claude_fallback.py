"""
ClaudeFallback — interpretacja niejednoznacznych odpowiedzi klienta przez Claude API.

Wywołuje Claude tylko gdy KeywordMatcher zwróci None (~20-30% tur).
Obsługuje też dygresje (limit 1 per rozmowa).

Zwracany DecisionResult (dict):
{
    "action":              "yes" | "no" | "optout" | "digression" | "unclear",
    "next_node":           str | None,
    "extracted_data":      dict,
    "digression_response": str | None,   # tekst odpowiedzi na dygresję
    "say_text":            str | None,   # tekst do wypowiedzenia przez TTS
}
"""
import json
import anthropic
import frappe


CLAUDE_MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 500

SYSTEM_PROMPT = """Jesteś asystentem biura rachunkowego Abacus. Prowadzisz rozmowę telefoniczną z klientem według ustalonego scenariusza.

Twoim zadaniem jest interpretacja odpowiedzi klienta i podjęcie decyzji o kolejnym kroku.

Zawsze odpowiadaj WYŁĄCZNIE w formacie JSON — bez żadnego tekstu przed ani po JSON. Nie używaj bloków kodu (```).

Format odpowiedzi:
{
  "action": "yes" | "no" | "optout" | "digression" | "unclear",
  "next_node": "nazwa_węzła lub null",
  "extracted_data": {},
  "digression_response": "tekst odpowiedzi na pytanie spoza scenariusza lub null",
  "say_text": "tekst który system ma wypowiedzieć lub null"
}

Zasady:
- "yes" — klient odpowiedział twierdząco na pytanie scenariusza
- "no" — klient odpowiedział przecząco
- "optout" — klient prosi o zaprzestanie automatycznego kontaktu
- "digression" — klient zadał pytanie spoza scenariusza (wypełnij digression_response)
- "unclear" — odpowiedź zupełnie niezrozumiała

Jeśli action=digression, w digression_response podaj krótką, uprzejmą odpowiedź PO POLSKU (max 2 zdania), a następnie wróć do scenariusza.
Jeśli action=yes lub no, wypełnij say_text tekstem który system ma wypowiedzieć (następne pytanie lub potwierdzenie).
Nigdy nie wymyślaj danych finansowych ani prawnych — powiedz że pracownik biura się skontaktuje.
"""


def _build_user_prompt(
    scenario_data: dict,
    current_node_id: str,
    speech_text: str,
    history: list[dict],
    digression_used: bool,
) -> str:
    """Buduje prompt użytkownika z kontekstem scenariusza i historią."""
    node = scenario_data.get("nodes", {}).get(current_node_id, {})

    history_text = ""
    if history:
        lines = []
        for turn in history[-6:]:  # ostatnie 6 tur (3 pary)
            speaker = "System" if turn["speaker"] == "system" else "Klient"
            lines.append(f"{speaker}: {turn['text']}")
        history_text = "\n".join(lines)

    digression_note = (
        "WAŻNE: Klient już wykorzystał limit dygresji (1). "
        "Jeśli to kolejna dygresja — zignoruj pytanie i wróć do scenariusza (action=unclear)."
        if digression_used
        else ""
    )

    return f"""Scenariusz — bieżący węzeł ({current_node_id}):
{json.dumps(node, ensure_ascii=False, indent=2)}

Historia rozmowy:
{history_text or "(brak historii — to pierwsza tura)"}

Odpowiedź klienta: "{speech_text}"

{digression_note}

Podejmij decyzję i zwróć JSON."""


class ClaudeFallback:

    @staticmethod
    def _get_api_key() -> str:
        settings = frappe.get_single("Voice Settings")
        key = settings.get_password("claude_api_key")
        if not key:
            frappe.throw("Claude API Key nie jest skonfigurowany w Voice Settings.")
        return key

    @staticmethod
    def decide(
        scenario_data: dict,
        current_node_id: str,
        speech_text: str,
        history: list[dict],
        digression_used: bool,
    ) -> dict:
        """
        Pyta Claude o interpretację odpowiedzi klienta.

        Returns:
            DecisionResult dict z action, next_node, extracted_data,
            digression_response, say_text.
        """
        api_key = ClaudeFallback._get_api_key()
        client = anthropic.Anthropic(api_key=api_key)

        user_prompt = _build_user_prompt(
            scenario_data=scenario_data,
            current_node_id=current_node_id,
            speech_text=speech_text,
            history=history,
            digression_used=digression_used,
        )

        try:
            message = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            raw = message.content[0].text.strip()
            result = json.loads(raw)
        except (json.JSONDecodeError, IndexError, KeyError) as e:
            frappe.log_error(
                title="ClaudeFallback: błąd parsowania odpowiedzi",
                message=f"Błąd: {e}\nOdpowiedź: {raw if 'raw' in dir() else 'brak'}",
            )
            return ClaudeFallback._unclear_result()
        except anthropic.APIError as e:
            frappe.log_error(
                title="ClaudeFallback: błąd API Claude",
                message=str(e),
            )
            return ClaudeFallback._unclear_result()

        # Walidacja wymaganych pól
        if "action" not in result:
            return ClaudeFallback._unclear_result()

        return {
            "action": result.get("action", "unclear"),
            "next_node": result.get("next_node"),
            "extracted_data": result.get("extracted_data", {}),
            "digression_response": result.get("digression_response"),
            "say_text": result.get("say_text"),
        }

    @staticmethod
    def _unclear_result() -> dict:
        """Bezpieczny fallback gdy Claude zawiedzie."""
        return {
            "action": "unclear",
            "next_node": None,
            "extracted_data": {},
            "digression_response": None,
            "say_text": None,
        }
