"""
ScenarioEngine — główny orkiestrator dialogu.

Łączy KeywordMatcher (szybkie dopasowanie) z ClaudeFallback (NLU)
i podejmuje decyzję o następnym kroku rozmowy.

Używany przez webhook handlers (Unit 3).

Przepływ per tura:
1. Pobierz bieżący węzeł z session["current_node"]
2. Keyword matching → wynik lub None
3. Jeśli None → Claude fallback
4. Zwróć DecisionResult
5. Caller aktualizuje sesję i buduje NCCO
"""
import json
from dataclasses import dataclass, field
from jinja2 import Environment, Undefined

from abacus_voice.engine.keyword_matcher import KeywordMatcher
from abacus_voice.engine.claude_fallback import ClaudeFallback
from abacus_voice.engine.session import SessionManager


# Akcje które silnik może zwrócić
ACTION_END = "end"        # Zakończ rozmowę (ścieżka sukcesu)
ACTION_GOTO = "goto"      # Przejdź do następnego węzła
ACTION_OPTOUT = "optout"  # Klient prosi o wypisanie
ACTION_UNCLEAR = "unclear"  # Niezrozumiała odpowiedź (po wyczerpaniu prób)
ACTION_DIGRESSION = "digression"  # Claude odpowiedział na dygresję, wróć do scenariusza


@dataclass
class DecisionResult:
    action: str
    say_text: str
    next_node: str | None = None
    extracted_data: dict = field(default_factory=dict)


def render_jinja(text: str, context_data: dict) -> str:
    """
    Renderuje tekst z placeholderami Jinja2.
    Nieznane zmienne są po cichu ignorowane (Undefined).
    """
    env = Environment(undefined=Undefined)
    try:
        return env.from_string(text).render(**context_data)
    except Exception:
        return text  # Jeśli render się nie uda, zwróć oryginalny tekst


class ScenarioEngine:

    def __init__(self, scenario_data: dict):
        """
        Args:
            scenario_data: Sparsowany JSON scenariusza (po Jinja2 render opening/node texts).
        """
        self.scenario_data = scenario_data
        self.nodes = scenario_data.get("nodes", {})

    @classmethod
    def from_rendered_json(cls, scenario_json: str, context_data: dict) -> "ScenarioEngine":
        """
        Parsuje JSON scenariusza i renderuje Jinja2 placeholdery w tekstach.
        Używany przy inicjowaniu rozmowy (Unit 4).

        Args:
            scenario_json: Surowy JSON string z CallScenario.scenario_json.
            context_data: Dict z danymi do wstrzyknięcia (np. {"client_name": "Jan Kowalski"}).

        Returns:
            ScenarioEngine gotowy do użycia.
        """
        data = json.loads(scenario_json)

        # Renderuj opening
        if "opening" in data:
            data["opening"] = render_jinja(data["opening"], context_data)

        # Renderuj teksty w węzłach
        for node_id, node in data.get("nodes", {}).items():
            for text_field in ("say", "say_template"):
                if text_field in node:
                    node[text_field] = render_jinja(node[text_field], context_data)
            for branch in ("on_yes", "on_no"):
                if branch in node and "say" in node[branch]:
                    node[branch]["say"] = render_jinja(node[branch]["say"], context_data)

        return cls(data)

    def process_response(self, speech_text: str, session: dict) -> tuple[DecisionResult, dict]:
        """
        Przetwarza odpowiedź klienta i zwraca decyzję oraz zaktualizowaną sesję.

        Args:
            speech_text: Tekst STT od Vonage.
            session: Bieżąca sesja (dict z Redis).

        Returns:
            (DecisionResult, updated_session)
        """
        current_node_id = session.get("current_node")
        node = self.nodes.get(current_node_id, {})
        context_data = session.get("context_data", {})
        digression_used = session.get("digression_used", False)

        # Dodaj turę klienta do historii
        session = SessionManager.add_history(session, "client", speech_text)

        # 1. Szybkie keyword matching
        match = KeywordMatcher.match(speech_text, node)

        if match == "optout":
            session["opt_out"] = True
            result = self._handle_optout()

        elif match == "yes":
            result, session = self._handle_yes(node, session)

        elif match == "no":
            result, session = self._handle_no(node, session)

        elif match is None:
            # 2. Claude fallback dla niejednoznacznych odpowiedzi
            result, session = self._handle_claude_fallback(
                speech_text=speech_text,
                node=node,
                current_node_id=current_node_id,
                session=session,
                digression_used=digression_used,
            )
        else:
            result = DecisionResult(
                action=ACTION_UNCLEAR,
                say_text=self.scenario_data.get(
                    "closing_error",
                    "Przepraszam, nie zrozumiałem. Skontaktuje się z Tobą pracownik biura."
                ),
            )

        # Dodaj odpowiedź systemu do historii
        if result.say_text:
            session = SessionManager.add_history(session, "system", result.say_text)

        # Aktualizuj węzeł w sesji
        if result.next_node:
            session["current_node"] = result.next_node

        # Aktualizuj extracted_data
        if result.extracted_data:
            session.setdefault("extracted_data", {})
            session["extracted_data"].update(result.extracted_data)

        return result, session

    # ------------------------------------------------------------------
    # Handlery per branch
    # ------------------------------------------------------------------

    def _handle_optout(self) -> DecisionResult:
        return DecisionResult(
            action=ACTION_OPTOUT,
            say_text=self.scenario_data.get(
                "closing_optout",
                "Rozumiem, nie będziemy się kontaktować automatycznie. Do widzenia."
            ),
        )

    def _handle_yes(self, node: dict, session: dict) -> tuple[DecisionResult, dict]:
        on_yes = node.get("on_yes", {})
        action = on_yes.get("action", ACTION_END)
        say_text = on_yes.get("say", "Dziękuję.")
        extracted = on_yes.get("extract", {})

        if action == ACTION_END:
            return DecisionResult(
                action=ACTION_END,
                say_text=say_text,
                extracted_data=extracted,
            ), session
        else:
            next_node = on_yes.get("next")
            return DecisionResult(
                action=ACTION_GOTO,
                say_text=say_text,
                next_node=next_node,
                extracted_data=extracted,
            ), session

    def _handle_no(self, node: dict, session: dict) -> tuple[DecisionResult, dict]:
        on_no = node.get("on_no", {})
        action = on_no.get("action", ACTION_END)
        say_text = on_no.get("say", "Rozumiem.")
        extracted = on_no.get("extract", {})

        if action == ACTION_END:
            return DecisionResult(
                action=ACTION_END,
                say_text=say_text,
                extracted_data=extracted,
            ), session
        elif action == "goto":
            next_node = on_no.get("next")
            # Jeśli następny węzeł ma capture_as — pobierz jego say_template
            next_node_data = self.nodes.get(next_node, {})
            if "say_template" in next_node_data:
                say_text = next_node_data["say_template"]
            return DecisionResult(
                action=ACTION_GOTO,
                say_text=say_text,
                next_node=next_node,
                extracted_data=extracted,
            ), session
        else:
            return DecisionResult(
                action=ACTION_END,
                say_text=say_text,
                extracted_data=extracted,
            ), session

    def _handle_claude_fallback(
        self,
        speech_text: str,
        node: dict,
        current_node_id: str,
        session: dict,
        digression_used: bool,
    ) -> tuple[DecisionResult, dict]:
        """Wywołuje Claude API i interpretuje wynik."""

        # Węzeł z capture_as — nie ma keywords, zbieramy wartość wprost
        if "capture_as" in node:
            captured_value = KeywordMatcher.capture_value(speech_text)
            extracted = {node["capture_as"]: captured_value}
            # Zastąp {{captured}} w extract szablonie
            raw_extract = node.get("extract", {})
            resolved_extract = {
                k: (captured_value if v == "{{captured}}" else v)
                for k, v in raw_extract.items()
            }
            resolved_extract.update(extracted)
            say = node.get("say_template", "Dziękuję, zanotowałem.")
            return DecisionResult(
                action=ACTION_END,
                say_text=say,
                extracted_data=resolved_extract,
            ), session

        # Standardowy Claude fallback
        claude_result = ClaudeFallback.decide(
            scenario_data=self.scenario_data,
            current_node_id=current_node_id,
            speech_text=speech_text,
            history=session.get("history", []),
            digression_used=digression_used,
        )

        action = claude_result.get("action", "unclear")

        if action == "digression":
            if digression_used:
                # Limit dygresji wyczerpany — ignoruj i wróć do scenariusza
                return self._repeat_current_question(current_node_id), session
            else:
                # Pierwsza dygresja — odpowiedz i wróć do bieżącego pytania
                session["digression_used"] = True
                digression_text = claude_result.get("digression_response", "")
                # Po odpowiedzi na dygresję powtórz bieżące pytanie
                current_question = self._get_node_question(current_node_id)
                combined = f"{digression_text} {current_question}".strip()
                return DecisionResult(
                    action=ACTION_DIGRESSION,
                    say_text=combined,
                    next_node=current_node_id,
                ), session

        elif action == "yes":
            return self._handle_yes(node, session)

        elif action == "no":
            return self._handle_no(node, session)

        elif action == "optout":
            session["opt_out"] = True
            return self._handle_optout(), session

        else:  # unclear
            return DecisionResult(
                action=ACTION_UNCLEAR,
                say_text=self.scenario_data.get(
                    "closing_error",
                    "Przepraszam, nie zrozumiałem. Skontaktuje się z Tobą pracownik biura."
                ),
            ), session

    def _get_node_question(self, node_id: str) -> str:
        """Zwraca tekst pytania bieżącego węzła (on_no.say jako proxy)."""
        node = self.nodes.get(node_id, {})
        # Użyj on_no.say jako "pytania" węzła — lub opening jeśli to pierwszy węzeł
        on_no = node.get("on_no", {})
        return on_no.get("say", self.scenario_data.get("opening", ""))

    def _repeat_current_question(self, node_id: str) -> DecisionResult:
        """Powtarza bieżące pytanie gdy limit dygresji wyczerpany."""
        question = self._get_node_question(node_id)
        return DecisionResult(
            action=ACTION_GOTO,
            say_text=f"Przepraszam, wróćmy do tematu. {question}".strip(),
            next_node=node_id,
        )

    def get_opening_text(self) -> str:
        """Zwraca tekst otwierający scenariusz (po Jinja2 render)."""
        return self.scenario_data.get("opening", "")
