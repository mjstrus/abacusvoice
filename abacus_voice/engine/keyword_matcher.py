"""
KeywordMatcher — szybkie dopasowanie słów kluczowych dla polskich odpowiedzi.

Logika:
1. Normalizuj tekst: lowercase, strip diakrytyki, strip interpunkcja
2. Sprawdź optout (priorytet najwyższy)
3. Sprawdź yes
4. Sprawdź no
5. Zwróć None jeśli brak dopasowania → Claude fallback

Dopasowanie substring — "już wysłałem" dopasuje słowo kluczowe "już".
"""
import unicodedata
import re


# Mapowanie polskich diakrytyk → ASCII (dla normalizacji)
_DIACRITIC_MAP = str.maketrans(
    "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ",
    "acelnoszzACELNOSZZ",
)


def normalize(text: str) -> str:
    """
    Normalizuje tekst do porównania:
    - lowercase
    - usuwa diakrytyki
    - usuwa interpunkcję
    - sprowadza wielokrotne spacje do jednej
    """
    text = text.lower()
    text = text.translate(_DIACRITIC_MAP)
    # Fallback unicodedata dla znaków spoza mapy
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _contains_any(normalized_text: str, keywords: list[str]) -> bool:
    """
    Sprawdza czy znormalizowany tekst zawiera którekolwiek ze słów kluczowych.

    Dla słów jednowyrazowych — dopasowanie dokładne na granicy słowa
    (unika false positive: "rozliczenie" zawiera "nie").
    Dla fraz wielowyrazowych — dopasowanie substring frazy w tekście.
    """
    words_in_text = set(normalized_text.split())
    for kw in keywords:
        normalized_kw = normalize(kw)
        if not normalized_kw:
            continue
        kw_words = normalized_kw.split()
        if len(kw_words) == 1:
            # Jednowyrazowe: exact word match
            if normalized_kw in words_in_text:
                return True
        else:
            # Wielowyrazowe: fraza jako substring
            if normalized_kw in normalized_text:
                return True
    return False


class KeywordMatcher:

    @staticmethod
    def match(speech_text: str, node: dict) -> str | None:
        """
        Dopasowuje odpowiedź klienta do kategorii na podstawie słów kluczowych węzła.

        Args:
            speech_text: Surowy tekst STT od klienta.
            node: Węzeł scenariusza (dict z keywords_yes, keywords_no, keywords_optout).

        Returns:
            "yes"    — odpowiedź twierdząca
            "no"     — odpowiedź przecząca
            "optout" — prośba o wypisanie z kontaktu
            None     — brak dopasowania → Claude fallback
        """
        if not speech_text or not speech_text.strip():
            return None

        normalized = normalize(speech_text)

        # Optout ma najwyższy priorytet — sprawdzamy pierwsza
        optout_keywords = node.get("keywords_optout", [])
        if optout_keywords and _contains_any(normalized, optout_keywords):
            return "optout"

        yes_keywords = node.get("keywords_yes", [])
        if yes_keywords and _contains_any(normalized, yes_keywords):
            return "yes"

        no_keywords = node.get("keywords_no", [])
        if no_keywords and _contains_any(normalized, no_keywords):
            return "no"

        return None

    @staticmethod
    def capture_value(speech_text: str) -> str:
        """
        Dla węzłów z capture_as — zwraca oczyszczony tekst odpowiedzi
        jako wartość do zapisania (np. termin "do piątku").
        """
        return speech_text.strip() if speech_text else ""
