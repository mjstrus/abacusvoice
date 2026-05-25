# SCENARIUSZE.md

## Tworzenie scenariuszy rozmów

Przewodnik jak pisać dialogu dla automatycznych rozmów.

---

## Podstawowa struktura

Scenariusz to JSON z trzema głównymi częściami:

```json
{
  "opening": "Tekst otwierający rozmowę",
  "nodes": {
    "q1": { ... },
    "q2": { ... }
  },
  "closing_optout": "Tekst gdy klient prosi o wypisanie",
  "closing_error": "Tekst gdy system nie zrozumie"
}
```

---

## 1. Opening — pytanie otwierające

```json
"opening": "Dzień dobry, {{ client_name }}. Czy dostarczyłeś już dokumenty?"
```

**Zmienne dostępne:**
- `{{ client_name }}` — nazwa klienta (automatycznie)
- `{{ client_id }}` — ID klienta
- Dowolne zmienne z `context_data` przy inicjowaniu

System zawsze zaczyna od `opening`, potem czeka na odpowiedź i przechodzi do węzła `q1`.

---

## 2. Nodes — sieć pytań

Każdy węzeł to jedno pytanie/interakcja. Węzeł musi mieć:

```json
"q1": {
  "keywords_yes": ["tak", "już", "wysłałem"],
  "keywords_no": ["nie", "jeszcze", "czekam"],
  "keywords_optout": ["nie dzwoń", "usuń", "wypisz"],
  "on_yes": { ... },
  "on_no": { ... }
}
```

### Keywords (słowa kluczowe)

System szuka tych słów w odpowiedzi klienta (po normalizacji):
- Małe/wielkie litery — ignoruje
- Diakrytyki — ignoruje
- Słowa mogą być częścią zdania

**Przykład:**
- Keyword: `"tak"`
- Odpowiedź klienta: `"Tak, już wysłałem wczoraj"`
- Wynik: ✅ dopasowanie `on_yes`

### on_yes, on_no — akcje

```json
"on_yes": {
  "say": "Dziękuję!",
  "action": "end",
  "extract": {"result": "TAK"}
}
```

**action — co zrobić:**
- `"end"` — zakończ rozmowę
- `"goto"` + `"next": "q2"` — przejdź do następnego węzła

**extract — co zapamiętać z tej rozmowy:**
```json
"extract": {"result": "TAK", "data_dodatkowa": "wartość"}
```

Te dane będą dostępne w `Call Log` → `extracted_data`.

---

## 3. Węzły ze zbieraniem danych — capture_as

Gdy chcesz aby system zapamiętał dokładnie to co powiedział klient:

```json
"q2": {
  "capture_as": "deadline",
  "say_template": "Dziękuję, zanotowałem: {{ captured }}",
  "action": "end",
  "extract": {"result": "NIE", "deadline": "{{captured}}"}
}
```

- `capture_as` — nazwa zmiennej
- `say_template` — tekst do wypowiedzenia (może zawierać `{{ captured }}` — co klient powiedział)
- `{{ captured }}` w `extract` — zostanie zastąpione odpowiedzią klienta

**Przykład:**
- Klient mówi: "Do piątku"
- System zapisuje: `{"deadline": "Do piątku"}`

---

## 4. Dygresje — pytania spoza scenariusza

Gdy klient zapyta coś spoza tematu, Claude odpowiada automatycznie:

```json
"q1": {
  "keywords_yes": ["tak"],
  "keywords_no": ["nie"],
  "on_yes": { ... },
  "on_no": { ... }
}
```

**Limit:** 1 dygresja per rozmowa. Po drugiej — system wznawia scenariusz.

**Przykład:**
- Scenariusz: "Czy dostarczyłeś dokumenty?"
- Klient: "Kiedy będzie PIT?"
- Claude: "PIT będzie gotowy w marcu. Wracając do tematu — czy dostarczyłeś dokumenty?"

---

## Pełny przykład scenariusza

### Scenariusz: "Windykacja składki ZUS"

```json
{
  "opening": "Dzień dobry, {{ client_name }}. To system biura rachunkowego Abacus. Dzwonimy w sprawie zaległej składki ZUS w kwocie {{ kwota }} zł za miesiąc {{ miesiac }}.",
  
  "rodo_message": "Rozmowa może być nagrywana w celach dokumentacyjnych. Czy się zgadzasz na kontynuowanie?",
  
  "nodes": {
    "q1": {
      "keywords_yes": ["tak", "zgadzam", "oczywiście", "dobrze"],
      "keywords_no": ["nie", "nie chcę", "sprzeciw"],
      "keywords_optout": ["nie dzwoń", "wypisz", "stop"],
      
      "on_yes": {
        "say": "Dziękuję. Czy mogliśmy liczyć na wpłatę zaległej składki do końca tego miesiąca?",
        "action": "goto",
        "next": "q2"
      },
      
      "on_no": {
        "say": "Rozumiem. Skontaktuje się z Tobą pracownik biura. Do widzenia.",
        "action": "end",
        "extract": {"status": "brak_zgody_rozmowa"}
      }
    },
    
    "q2": {
      "keywords_yes": ["tak", "będzie", "mogę", "uda się"],
      "keywords_no": ["nie", "nie mogę", "nie dam rady"],
      
      "on_yes": {
        "say": "Świetnie! Będziemy czekać na wpłatę. Dziękuję!",
        "action": "end",
        "extract": {"status": "obiecana_wpłata", "termin": "koniec miesiąca"}
      },
      
      "on_no": {
        "say": "Rozumiem. Do kiedy moglibyśmy liczyć na wpłatę?",
        "action": "goto",
        "next": "q3"
      }
    },
    
    "q3": {
      "capture_as": "alt_deadline",
      "say_template": "Dziękuję, zanotowałem wpłatę do {{ captured }}. Będziemy czekać.",
      "action": "end",
      "extract": {
        "status": "odroczenie",
        "termin_alternatywny": "{{captured}}"
      }
    }
  },
  
  "closing_optout": "Rozumiem. Nie będziemy więcej dzwonić automatycznie. Pracownik biura skontaktuje się z Tobą bezpośrednio. Do widzenia.",
  
  "closing_error": "Przepraszam, nie zrozumiałem Twojej odpowiedzi. Skontaktuje się z Tobą pracownik biura. Do widzenia."
}
```

### Jak to działa:

1. **opening** — system czyta komunikat o składce
2. **RODO** — informuje o nagrywaniu (zawsze na początku)
3. **q1** — czy klient zgadza się na rozmowę?
   - TAK → przejdź do q2
   - NIE → skończ, zanotuj "brak zgody"
4. **q2** — czy będzie wpłata do końca miesiąca?
   - TAK → koniec, zanotuj "obiecana"
   - NIE → przejdź do q3
5. **q3** — do kiedy może wpłacić? (capture zapamiętuje dokładnie co powiedział)
   - Koniec rozmowy, zanotuj termin

---

## Best practices

### ✅ Dobrze

```json
"keywords_yes": ["tak", "już", "wysłałem", "dostarczyłem", "oczywiście", "zgadzam"],
"keywords_no": ["nie", "jeszcze", "czekam", "brakuje", "problem", "nie mogę"]
```

- **Naturalne słowa** — takie które mówią ludzie
- **Różne warianty** — dla elastyczności
- **Słowa powiązane tematycznie** — "wysłałem" dla "dokumenty"

### ❌ Źle

```json
"keywords_yes": ["y", "si", "ok"],  // Za krótkie, mogą być falszywym dopasowaniem
"keywords_no": ["n"],               // "n" będzie w każdym słowie zawierającym "n"
"keywords_optout": ["nie"]          // Kolizja z "nie" (brak dokumentów)
```

---

## Testowanie scenariusza

1. Wejdź w Frappe → **Call Scenario** → Utwórz nowy
2. Wklej JSON w pole **Scenario JSON**
3. Kliknij **Save**
4. Otwórz kartę klienta → **Abacus Voice** → **Zadzwoń** → wybierz scenariusz
5. Obserwuj logę w **Call Log** → **extracted_data** (zobaczysz co system zapamiętał)

---

## Personalizacja — zmienne Jinja2

Możesz wstawiać zmienne w każdy tekst:

```json
"opening": "Dzień dobry, {{ client_name }}. Wpadł nam na biurko rachunek za {{ service }} w kwocie {{ amount }} zł."
```

Zmienne dostępne:
- `client_name` — nazwa klienta (automatycznie)
- `client_id` — ID klienta
- Cokolwiek przekażesz w `context_data` przy inicjowaniu:

```python
frappe.call("abacus_voice.api.initiate_call",
    client_id="KLIENT-001",
    scenario_id="Windykacja",
    context_data={"service": "audyt", "amount": "2500"}
)
```

---

## Następnie

Przejdź do **API.md** — jak wywoływać rozmowy z innych modułów Frappe.
