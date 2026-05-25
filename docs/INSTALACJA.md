# INSTALACJA.md

## Instalacja abacus_voice na Docker Compose

Instrukcja krok po kroku dla środowiska Docker z Frappe.

---

## Wymagania

- Docker i Docker Compose zainstalowane
- Frappe zainstalowane w kontenerze
- Dostęp SSH do serwera VPS
- Konto na GitHub (jeśli pobierasz z repozytorium)

---

## Krok 1: Ustal nazwę kontenera

```bash
docker ps
```

Szukasz kontenera z Frappe — zazwyczaj `frappe_backend_1`, `frappe_web_1` lub podobnie. Zanotuj nazwę.

Przykład output:
```
CONTAINER ID   IMAGE           STATUS         NAMES
abc123def456   frappe:latest   Up 2 hours     frappe_backend_1
xyz789uvw012   frappe:latest   Up 2 hours     frappe_worker_1
```

W tym przypadku używamy `frappe_backend_1`.

---

## Krok 2: Pobierz aplikację z GitHub

**Opcja A — przez bench (polecane)**

```bash
docker exec -it frappe_backend_1 bash
```

Wewnątrz kontenera:

```bash
cd /home/frappe/frappe-bench

bench get-app https://github.com/mjstrus/abacusvoice.git

# Wyjdź z kontenera
exit
```

**Opcja B — przez docker cp (jeśli nie masz dostępu do git w kontenerze)**

Na swoim komputerze rozpakuj ZIP lub sklonuj repozytorium, potem:

```bash
docker cp abacus_voice/ frappe_backend_1:/home/frappe/frappe-bench/apps/
```

---

## Krok 3: Zainstaluj aplikację w Frappe

```bash
docker exec -it frappe_backend_1 bash
```

Wewnątrz kontenera:

```bash
cd /home/frappe/frappe-bench

# Zainstaluj zależności Python
bench pip install -e apps/abacus_voice

# Zainstaluj aplikację na stronie
# Podmień "twoja-strona" na rzeczywistą nazwę strony (np. "abacus.pl")
bench --site twoja-strona install-app abacus_voice

# Migracja — tworzy DocTypes w bazie danych
bench --site twoja-strona migrate

# Wyjdź z kontenera
exit
```

---

## Krok 4: Restart kontenera

```bash
docker restart frappe_backend_1
```

Czekaj ~30 sekund na restart.

---

## Krok 5: Weryfikacja instalacji

Wejdź do Frappe desk na przeglądarce (https://twoja-strona):

1. Wyszukaj **Voice Settings** (po lewej "Search")
2. Powinno pojawić się w menu — instalacja powiodła się
3. Jeśli nie widać — sprawdź logi:

```bash
docker exec -it frappe_backend_1 bash
cd /home/frappe/frappe-bench
bench --site twoja-strona error-log
exit
```

---

## Krok 6: Konfiguracja Voice Settings

Wejdź w Frappe → **Voice Settings** i uzupełnij:

### Vonage
- **Vonage Application ID** — z [Vonage Dashboard](https://dashboard.vonage.com) → Your Applications
- **Vonage Private Key** — zawartość pliku `.key` (copy-paste całego pliku, w tym `-----BEGIN PRIVATE KEY-----` i `-----END PRIVATE KEY-----`)
- **Vonage Signature Secret** — z Vonage Dashboard → API Settings → Signature secret
- **Vonage Phone Number** — Twój numer wychodzący, np. `+48221234567`

### Claude API
- **Claude API Key** — z [console.anthropic.com](https://console.anthropic.com) → API keys

### Webhooks
- **Webhook Base URL** — URL gdzie Vonage będzie wysyłać callback'i

  Jeśli testujesz lokalnie — użyj **ngrok**:
  ```bash
  ngrok http 8000
  ```
  Wklej URL (np. `https://abc123.ngrok.io/api/method/abacus_voice.webhook`)

  Jeśli masz publiczny serwer — wpisz domenę: `https://twoja-domena.pl/api/method/abacus_voice.webhook`

### Inne
- **Osoba do zadań opt-out** — użytkownik Frappe (np. Administrator) który otrzymuje Tasks gdy klient prosi o wypisanie

---

## Krok 7: Konfiguracja Vonage Dashboard

Żeby Vonage wiedział gdzie wysyłać callback'i:

1. Wejdź na [Vonage Dashboard](https://dashboard.vonage.com) → Your Applications → Twoja aplikacja Voice
2. Kliknij **Edit**
3. Uzupełnij:
   - **Answer URL**: `https://twoja-domena.pl/api/method/abacus_voice.webhook.voice_answer`
   - **Event URL**: `https://twoja-domena.pl/api/method/abacus_voice.webhook.voice_event`

Zapisz.

---

## Krok 8: Test

Wejdź w Frappe → otwórz kartę klienta → menu **Abacus Voice** → **Zadzwoń**

Jeśli pojawi się dialog — wszystko działa!

---

## Troubleshooting

### Błąd "abacus_voice not found" po instalacji

```bash
docker exec -it frappe_backend_1 bash
cd /home/frappe/frappe-bench
bench clear-cache
bench restart
exit
```

### Błąd przy `bench get-app`

Git może być niedostępny w kontenerze. Użyj **Opcja B** (docker cp).

### Błąd przy migrate

```bash
docker exec -it frappe_backend_1 bash
cd /home/frappe/frappe-bench
bench --site twoja-strona migrate --verbose
exit
```

Wklej błąd — pomogę.

### ngrok: "Connection refused"

Upewnij się że Frappe działa lokalnie na porcie 8000:
```bash
docker ps
# Czy kontener jest UP?
```

---

## Następnie

Przejdź do **KONFIGURACJA.md** — szczegółowa konfiguracja Voice Settings i Vonage.
