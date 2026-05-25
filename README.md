# abacus_voice

Frappe custom app — moduł automatycznych rozmów telefonicznych dla biura rachunkowego Abacus.

System dzwoni do klientów, prowadzi naturalny dialog głosowy według zdefiniowanego scenariusza, zbiera odpowiedzi i zapisuje wynik w Frappe CRM.

## Funkcje

- Outbound calls przez Vonage Voice API (polski numer +48)
- Naturalny dialog po polsku — keyword matching + Claude API jako fallback NLU
- Scenariusze rozmów definiowane jako JSON w Frappe (dowolna złożoność)
- Automatyczne retry gdy klient nie odbiera (konfigurowalne per scenariusz)
- Opt-out — wykrywanie prośby o wypisanie, flaga na kliencie, Task dla obsługi
- Logi rozmów z transkrypcją i nagraniem audio (Vonage recording)
- Anulowanie zaplanowanych retry z poziomu Frappe UI
- API dla innych modułów Frappe (windykacja, generator pism)

## Stack

- **Frappe** (self-hosted) — hub, DocTypes, scheduler, UI
- **Vonage Voice API** — outbound calls, STT (ASR), TTS, nagrywanie
- **Claude API** (Anthropic) — NLU fallback dla niejednoznacznych odpowiedzi
- **Redis** — session state aktywnych rozmów
- **Jinja2** — personalizacja scenariuszy danymi klienta

## Instalacja

### Wymagania

- Frappe >= 14.x
- Python >= 3.10
- Redis (standardowo przy Frappe)
- Konta: [Vonage](https://vonage.com), [Anthropic Claude](https://console.anthropic.com)

### Przez bench

```bash
cd /home/frappe/frappe-bench

bench get-app https://github.com/mjstrus/abacusvoice.git
bench --site twoja-strona install-app abacus_voice
bench --site twoja-strona migrate
bench restart
```

### Przez docker cp (jeśli używasz Docker)

```bash
# Skopiuj folder do kontenera
docker cp abacus_voice/ frappe_backend_1:/home/frappe/frappe-bench/apps/

# Wejdź do kontenera
docker exec -it frappe_backend_1 bash

# Zainstaluj
cd /home/frappe/frappe-bench
bench pip install -e apps/abacus_voice
bench --site twoja-strona install-app abacus_voice
bench --site twoja-strona migrate
exit

# Restart
docker restart frappe_backend_1
```

## Konfiguracja po instalacji

1. Wejdź w Frappe desk → wyszukaj **Voice Settings**
2. Uzupełnij:
   - **Vonage Application ID** — z Vonage Dashboard → Your Applications
   - **Vonage Private Key** — zawartość pliku `.key` wygenerowanego przy tworzeniu aplikacji Vonage
   - **Vonage Signature Secret** — z Vonage Dashboard → API Settings → Signature secret
   - **Vonage Phone Number** — numer wychodzący w formacie `+48...`
   - **Claude API Key** — z [console.anthropic.com](https://console.anthropic.com)
   - **Webhook Base URL** — publiczny URL serwera, np. `https://twojadomena.pl/api/method/abacus_voice.webhook`
   - **Osoba do zadań opt-out** — użytkownik Frappe który otrzymuje zadania gdy klient prosi o wypisanie

3. W **Vonage Dashboard → Voice Application → Edit**:
   - Answer URL: `https://twojadomena.pl/api/method/abacus_voice.webhook.voice_answer`
   - Event URL: `https://twojadomena.pl/api/method/abacus_voice.webhook.voice_event`

4. Utwórz pierwszy scenariusz w **Call Scenario**

## Tworzenie scenariusza

W Frappe desk → Call Scenario → Nowy:

```json
{
  "opening": "Dzień dobry, {{ client_name }}. Czy dostarczyłeś już komplet dokumentów?",
  "nodes": {
    "q1": {
      "keywords_yes": ["tak", "już", "wysłałem", "dostarczyłem", "oczywiście"],
      "keywords_no": ["nie", "jeszcze", "czekam", "brakuje", "problem"],
      "keywords_optout": ["nie dzwoń", "usuń", "wypisz", "stop"],
      "on_yes": {
        "say": "Dziękuję, miłego dnia!",
        "action": "end",
        "extract": {"result": "TAK"}
      },
      "on_no": {
        "say": "Rozumiem. Do którego dnia dostarczysz komplet dokumentów?",
        "action": "goto",
        "next": "q2"
      },
      "on_unclear": "claude_fallback"
    },
    "q2": {
      "capture_as": "deadline",
      "say_template": "Dziękuję, zanotowałem termin. Do zobaczenia!",
      "action": "end",
      "extract": {"result": "NIE", "deadline": "{{captured}}"}
    }
  },
  "closing_optout": "Rozumiem, nie będziemy kontaktować się automatycznie. Do widzenia.",
  "closing_error": "Przepraszam, nie zrozumiałem. Skontaktuje się z Tobą pracownik biura."
}
```

## Inicjowanie rozmowy

### Z Frappe UI
Otwórz kartę klienta → menu **Abacus Voice** → **Zadzwoń**

### Z innego modułu Frappe
```python
frappe.call("abacus_voice.api.initiate_call",
    client_id="KLIENT-001",
    scenario_id="Dokumenty Check",
    context_data={"client_name": "Jan Kowalski", "kwota": "1500"}
)
```

## Testy

```bash
# Lokalnie (bez Frappe)
pip install pytest jinja2 anthropic
python -m pytest abacus_voice/tests/ --ignore=abacus_voice/tests/test_doctypes.py -v

# Na Frappe
bench run-tests --app abacus_voice
```

## Struktura DocTypes

| DocType | Opis |
|---------|------|
| Call Scenario | Scenariusze dialogów (JSON) |
| Call Log | Logi zakończonych rozmów z transkrypcją |
| Call Queue | Kolejka retry dla nieodebranych połączeń |
| Voice Settings | Konfiguracja Vonage, Claude, webhooks (Single) |

## Licencja

MIT
