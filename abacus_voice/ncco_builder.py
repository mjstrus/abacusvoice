"""
NccoBuilder — buduje listy NCCO (Nexmo Call Control Objects) dla Vonage Voice API.

Vonage oczekuje tablicy JSON z akcjami. Każda akcja to dict z polem "action".
Zamiast zewnętrznej biblioteki — prosty builder oparty na dict/list.

Dokumentacja NCCO: https://developer.vonage.com/en/voice/voice-api/ncco-reference
"""


class NccoBuilder:

    @staticmethod
    def talk(text: str, language: str = "pl-PL", style: int = 1) -> dict:
        """
        Akcja `talk` — text-to-speech.

        Args:
            text: Tekst do wypowiedzenia.
            language: Kod języka (domyślnie pl-PL).
            style: Styl głosu (0=kobieta, 1=mężczyzna — zależy od providera).
        """
        return {
            "action": "talk",
            "text": text,
            "language": language,
            "style": style,
        }

    @staticmethod
    def input_speech(event_url: str, language: str = "pl-PL", end_on_silence: int = 2) -> dict:
        """
        Akcja `input` z rozpoznawaniem mowy (ASR).

        Args:
            event_url: URL do którego Vonage wyśle transkrypcję.
            language: Język rozpoznawania (domyślnie pl-PL).
            end_on_silence: Sekundy ciszy po których Vonage kończy nagrywanie.
        """
        return {
            "action": "input",
            "type": ["speech"],
            "speech": {
                "language": language,
                "endOnSilence": end_on_silence,
                "maxDuration": 60,
            },
            "eventUrl": [event_url],
        }

    @staticmethod
    def hangup() -> dict:
        """Akcja `hangup` — rozłącza połączenie."""
        return {"action": "hangup"}

    @staticmethod
    def record(event_url: str) -> dict:
        """
        Akcja `record` — nagrywa rozmowę.
        Zazwyczaj umieszczana na początku NCCO.
        """
        return {
            "action": "record",
            "eventUrl": [event_url],
            "endOnSilence": 3,
            "beepStart": False,
        }

    # ------------------------------------------------------------------
    # Kompozyty — gotowe NCCO dla typowych scenariuszy
    # ------------------------------------------------------------------

    @staticmethod
    def opening_ncco(
        rodo_text: str,
        opening_text: str,
        asr_event_url: str,
        record_event_url: str | None = None,
    ) -> list[dict]:
        """
        NCCO na start rozmowy:
        1. [opcjonalnie] record
        2. talk: komunikat RODO
        3. talk: pierwsze pytanie scenariusza
        4. input speech → ASR

        Args:
            rodo_text: Komunikat identyfikujący + RODO.
            opening_text: Pierwsze pytanie scenariusza.
            asr_event_url: URL dla ASR eventUrl.
            record_event_url: URL dla nagrania (opcjonalnie).
        """
        ncco = []
        if record_event_url:
            ncco.append(NccoBuilder.record(record_event_url))
        ncco.append(NccoBuilder.talk(rodo_text))
        ncco.append(NccoBuilder.talk(opening_text))
        ncco.append(NccoBuilder.input_speech(asr_event_url))
        return ncco

    @staticmethod
    def question_ncco(question_text: str, asr_event_url: str) -> list[dict]:
        """
        NCCO z pytaniem i oczekiwaniem na odpowiedź:
        1. talk: pytanie
        2. input speech → ASR
        """
        return [
            NccoBuilder.talk(question_text),
            NccoBuilder.input_speech(asr_event_url),
        ]

    @staticmethod
    def closing_ncco(closing_text: str) -> list[dict]:
        """
        NCCO kończące rozmowę:
        1. talk: komunikat zamykający
        2. hangup
        """
        return [
            NccoBuilder.talk(closing_text),
            NccoBuilder.hangup(),
        ]
