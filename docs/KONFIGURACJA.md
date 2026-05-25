# KONFIGURACJA.md

## Konfiguracja Voice Settings i Vonage

Przewodnik krok po kroku do pełnej konfiguracji modułu.

---

## Część 1: Vonage Voice API

### Założenie konta

1. Wejdź na [vonage.com](https://vonage.com)
2. Kliknij **Sign up** → **Vonage API Accounts**
3. Załóż konto — dostajesz kredyt trial (darmowe rozmowy na testy)

### Tworzenie Voice Application

1. Wejdź na [Vonage Dashboard](https://dashboard.vonage.com)
2. Menu → **Voice** → **Create an application**
3. Uzupełnij:
   - **Application name**: `abacus_voice` (lub inna nazwa)
   - **Accept incoming calls?**: TAK
   - **Answer URL**: `https://twoja-domena.pl/api/method/abacus_voice.webhook.voice_answer`
   - **Event URL**: `https://twoja-domena.pl/api/method/abacus_voice.webhook.voice_event`

4. **Generate public and private key** — pobierze się plik `.key` — **zachowaj go bezpiecznie**
5. Kliknij **Create Application**

### Pobranie danych

Po utworzeniu aplikacji zobaczysz:
- **Application ID** — skopiuj
- **Private Key** — zawartość pliku `.key`
- **Signature Secret** — z Settings → API Settings

### Przydzielenie numeru telefonu

1. W Vonage Dashboard → **Numbers** → **Buy Numbers**
2. Wybierz kraj (Polska +48), typ (Mobile)
3. Kup numer (trial ma darmowe)
4. W **Your Numbers** → przydziel numer do Voice Application

---

## Część 2: Claude API

### Założenie konta

1. Wejdź na [console.anthropic.com](https://console.anthropic.com)
2. **Sign up** → załóż darmowe konto
3. Dodaj metodę płatności (kartę) — będzie Ci naliczane za API (kilka groszy za rozmowę)

### Pobranie API Key

1. W console → **Settings** → **API Keys**
2. **Create new API key**
3. Skopiuj klucz (widoczny tylko raz)

---

## Część 3: Frappe Voice Settings

Wejdź w Frappe desk → wyszukaj **Voice Settings**.

### Tab: Vonage

| Pole | Wartość | Źródło |
|------|---------|--------|
| **Vonage Application ID** | `abc123def456` | Vonage Dashboard → Your Applications |
| **Vonage Private Key** | `-----BEGIN PRIVATE KEY-----` ... | Plik `.key` z Vonage (copy-paste całości) |
| **Vonage Signature Secret** | `abcd1234efgh5678` | Vonage Dashboard → Settings → API Settings → Signature secret |
| **Vonage Phone Number** | `+48221234567` | Vonage Dashboard → Your Numbers |

### Tab: Claude API

| Pole | Wartość | Źródło |
|------|---------|--------|
| **Claude API Key** | `sk-ant-v0-abc...` | console.anthropic.com → API Keys |

### Tab: Webhooks

| Pole | Wartość | Uwaga |
|------|---------|-------|
| **Webhook Base URL** | `https://twoja-domena.pl/api/method/abacus_voice.webhook` | Bez `/` na końcu |
| **Osoba do zadań opt-out** | `administrator` | Użytkownik Frappe który dostaje Tasks |

---

## Weryfikacja konfiguracji

```bash
docker exec -it frappe_backend_1 bash
cd /home/frappe/frappe-bench

# Test połączenia z Vonage (opcjonalnie)
bench --site twoja-strona console
>>> from abacus_voice.api import _get_vonage_client
>>> from frappe import get_single
>>> settings = get_single("Voice Settings")
>>> client = _get_vonage_client(settings)
>>> print("Vonage OK")

# Test Claude API
>>> from abacus_voice.engine.claude_fallback import ClaudeFallback
>>> print("Claude OK")

exit
exit
```

Jeśli nie ma błędów — konfiguracja OK.

---

## Testowa rozmowa

### 1. Utwórz scenariusz testowy

Wejdź w Frappe → **Call Scenario** → **Nowy dokument**

```json
{
  "opening": "Cześć, testujemy system. Powiedz: TAK",
  "nodes": {
    "q1": {
      "keywords_yes": ["tak", "yes"],
      "keywords_no": ["nie", "no"],
      "keywords_optout": ["stop"],
      "on_yes": {
        "say": "Super! Test powiódł się. Do widzenia!",
        "action": "end",
        "extract": {"result": "TAK"}
      },
      "on_no": {
        "say": "Rozumiem. Dziękuję!",
        "action": "end",
        "extract": {"result": "NIE"}
      }
    }
  },
  "closing_optout": "Rozumiem, nie będę dzwonić.",
  "closing_error": "Przepraszam, błąd techniczny."
}
```

Zapisz jako **Call Scenario** o nazwie `TEST`.

### 2. Otwórz kartę klienta

**Abacus Voice** → **Zadzwoń**

### 3. Wybierz scenariusz TEST

Powinien się odezwać automatycznie.

---

## ngrok dla testów lokalnych

Jeśli testujesz na maszynie lokalnej:

```bash
# Zainstaluj ngrok (raz)
# Windows: https://ngrok.com/download
# Mac: brew install ngrok

# Uruchom
ngrok http 8000

# Dostaniesz URL: https://abc123.ngrok.io
```

Wpisz ten URL w **Webhook Base URL** (Voice Settings).

W Vonage Dashboard ustaw:
- Answer URL: `https://abc123.ngrok.io/api/method/abacus_voice.webhook.voice_answer`
- Event URL: `https://abc123.ngrok.io/api/method/abacus_voice.webhook.voice_event`

---

## Troubleshooting

### "Invalid private key"

Upewnij się że skopiowałeś **cały** plik `.key`:
```
-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQE...
...
-----END PRIVATE KEY-----
```

### "Vonage API error: 401 Unauthorized"

Sprawdź:
- Czy Application ID jest poprawny?
- Czy Private Key jest pełny i bez dodatkowych spacji?
- Czy numer telefonu jest przydzielony do aplikacji?

### "Claude API error: 401"

- API Key jest zapamiętany w Frappe z password encryption
- Sprawdź czy Key jest prawidłowy na console.anthropic.com
- Jeśli miał 90-dniowy limit — wygeneruj nowy

### Webhook nie otrzymuje żądań od Vonage

- Czy **Webhook Base URL** jest dostępny publicznie? (test: `curl https://url.pl/api/method/abacus_voice.webhook.voice_answer`)
- Czy w Vonage Dashboard URLs są takie same jak w Voice Settings?
- Jeśli używasz ngrok — czy sesja ngrok wciąż działa?

---

## Następnie

Przejdź do **SCENARIUSZE.md** — jak pisać dialogu dla rozmów.
