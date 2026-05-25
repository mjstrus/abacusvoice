# API.md

## API abacus_voice

Jak wywoływać rozmowy z innych modułów Frappe i integrować z biznesową logiką.

---

## Główne endpointy

### `initiate_call` — inicjuj rozmowę

Wejście do całego systemu. Zainicjuje rozmowę telefoniczną do klienta.

**Kod:**
```python
frappe.call("abacus_voice.api.initiate_call",
    args={
        "client_id": "KLIENT-001",
        "scenario_id": "Dokumenty Check",
        "context_data": {
            "client_name": "Jan Kowalski",
            "kwota": "1500",
            "termin": "31 maja"
        }
    },
    callback(r) {
        if (!r.exc) {
            console.log("Rozmowa zainicjowana:", r.message.conversation_uuid);
        }
    }
)
```

**Parametry:**

| Parametr | Typ | Wymagany | Opis |
|----------|-----|----------|------|
| `client_id` | string | ✅ | Nazwa dokumentu Customer w Frappe |
| `scenario_id` | string | ✅ | Nazwa dokumentu Call Scenario |
| `context_data` | dict/JSON | ❌ | Dict lub JSON string z danymi do Jinja2 render scenariusza |

**Response:**
```json
{
  "status": "initiated",
  "conversation_uuid": "CON-abc123def456"
}
```

**Wyjątki:**
```python
# Klient ma opt-out
frappe.ValidationError: "Klient ... jest wypisany z kontaktu automatycznego"

# Scenariusz nieaktywny
frappe.ValidationError: "Scenariusz ... jest nieaktywny"

# Brak numeru telefonu
frappe.ValidationError: "Klient nie ma przypisanego numeru telefonu"

# Błąd Vonage API
Exception: "Nie udało się zainicjować połączenia przez Vonage: ..."
```

---

## Przykłady integracji

### 1. Przycisk w Customer form

Dodaj przycisk do Customer → Action → "Zadzwoń w sprawie faktury zalegającej"

```javascript
frappe.ui.form.on("Customer", {
    refresh(frm) {
        frm.add_custom_button(__("Zadzwoń"), function() {
            frappe.call({
                method: "abacus_voice.api.initiate_call",
                args: {
                    client_id: frm.doc.name,
                    scenario_id: "Windykacja",
                    context_data: {
                        client_name: frm.doc.customer_name,
                        kwota: 1500,
                        termin: "7 dni"
                    }
                },
                callback(r) {
                    if (!r.exc) {
                        frappe.msgprint("Rozmowa zainicjowana");
                    }
                }
            });
        });
    }
});
```

### 2. Automatyczne rozmowy z doctype'u

Np. Invoice — gdy faktura jest zaległa 30 dni, automatycznie dzwoń do klienta.

```python
# W Server Script (Frappe automation)
@frappe.whitelist()
def remind_overdue_invoice(invoice_name):
    """Rozmowa w sprawie zalegającej faktury."""
    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    customer = invoice.customer
    overdue_days = (frappe.utils.today() - invoice.due_date).days
    
    frappe.call("abacus_voice.api.initiate_call",
        args={
            "client_id": customer,
            "scenario_id": "Windykacja Faktury",
            "context_data": {
                "client_name": invoice.customer_name,
                "invoice_number": invoice_name,
                "amount": invoice.grand_total,
                "overdue_days": overdue_days
            }
        }
    )
    
    frappe.log_info(f"Rozmowa windykacyjna: {customer}")
```

### 3. Masowe rozmowy — batch processing

Dzwoń do wszystkich klientów ze statusem "Oczekuje kontaktu".

```python
# Server Script lub Custom Script
def initiate_batch_calls():
    """Zainicjuj rozmowy dla klientów w statusie 'Oczekuje'."""
    customers = frappe.get_all(
        "Customer",
        filters={"customer_status": "Oczekuje", "voice_opt_out": 0},
        fields=["name", "customer_name", "mobile_no"],
        limit=10
    )
    
    for customer in customers:
        try:
            frappe.call("abacus_voice.api.initiate_call",
                args={
                    "client_id": customer.name,
                    "scenario_id": "Kontakt Powitacyjny"
                }
            )
            frappe.db.set_value("Customer", customer.name, "last_call_at", frappe.utils.now())
        except Exception as e:
            frappe.log_error(f"Błąd przy dzwonieniu do {customer.name}: {e}")

if __name__ == "__main__":
    initiate_batch_calls()
```

### 4. Webhook — przepływ z innego systemu

Gdy coś się stanie w innym systemie, wyzwól rozmowę.

```python
# API endpoint
@frappe.whitelist(allow_guest=True)
def webhook_from_external_system():
    """Webhook z zewnętrznego systemu."""
    data = frappe.request.json
    
    # Zweryfikuj token
    if data.get("token") != frappe.conf.external_system_token:
        return {"error": "Unauthorized"}
    
    # Zainicjuj rozmowę
    result = frappe.call("abacus_voice.api.initiate_call",
        args={
            "client_id": data.get("customer_id"),
            "scenario_id": "Potwierdzenie Zamówienia",
            "context_data": {
                "order_id": data.get("order_id"),
                "amount": data.get("amount")
            }
        }
    )
    
    return {"status": "success", "conversation_uuid": result.get("conversation_uuid")}
```

---

## Odczyt wyników rozmowy

### Call Log — logi rozmów

Po zakończeniu rozmowy system tworzy rekord **Call Log** z:

```python
call_log = frappe.get_doc("Call Log", conversation_uuid)

print(call_log.status)              # "completed", "unanswered", "failed", "opt-out"
print(call_log.transcript)          # Cały dialog
print(call_log.extracted_data)      # JSON z zebranymi danymi
print(call_log.recording_url)       # Link do nagrania (Vonage)
print(call_log.started_at)          # Kiedy się zaczęła
print(call_log.ended_at)            # Kiedy się skończyła
```

### Dane zebrane — extracted_data

Klient odpowiedział na pytania scenariusza — dane zapisane w `extracted_data`:

```json
{
  "result": "TAK",
  "deadline": "Do piątku",
  "status": "obiecana_wpłata"
}
```

Możesz je potem przetworzyć:

```python
call_log = frappe.get_doc("Call Log", conversation_uuid)
data = json.loads(call_log.extracted_data)

if data.get("result") == "TAK":
    # Klient potwierdził
    frappe.db.set_value("Customer", call_log.client_id, "confirmed", 1)
elif data.get("result") == "NIE":
    # Klient nie potwierdził
    deadline = data.get("deadline")
    frappe.db.set_value("Customer", call_log.client_id, "follow_up_deadline", deadline)
```

### Opt-out — klient prosi o wypisanie

Gdy klient powie "nie dzwoń", system automatycznie:

1. Ustawia flagę na Customer: `voice_opt_out = 1`
2. Tworzy Task dla obsługi
3. Zapisuje `call_log.status = "opt-out"`

W kodzie:

```python
def check_for_optouts():
    opted_out = frappe.get_all(
        "Call Log",
        filters={"status": "opt-out", "opt_out_processed": 0},
        fields=["client_id"]
    )
    
    for log in opted_out:
        # Wyślij email do klienta z potwierdzeniem
        frappe.sendmail(
            recipients=[log.client_id.email],
            subject="Potwierdzenie wypisania z kontaktu automatycznego",
            message="Twoja prośba została przyjęta..."
        )
```

---

## Retry — ponowne próby

Gdy klient nie odbierze, system automatycznie tworzy rekord **Call Queue** z retry.

Możesz wczytać pending retry:

```python
pending = frappe.get_all(
    "Call Queue",
    filters={"status": "pending"},
    fields=["client_id", "scenario", "scheduled_at", "attempt_number"]
)

for queue in pending:
    print(f"Retry dla {queue.client_id}: próba {queue.attempt_number} o {queue.scheduled_at}")
```

Lub anulować retry ręcznie:

```python
frappe.call("abacus_voice.scheduler.cancel_queue_item",
    args={"queue_name": "CQUEUE-001"},
    callback(r) {
        if (r.message.status === "cancelled") {
            frappe.show_alert("Retry anulowany");
        }
    }
)
```

---

## Server Script — szybka integracja

Bez pisania kodu, możesz użyć **Server Script** w Frappe:

```python
# Settings → Customize Form → Add Script (Server Script)

if doc.name == "KLIENT-001" and doc.flags.via_api:
    frappe.call("abacus_voice.api.initiate_call",
        args={
            "client_id": doc.name,
            "scenario_id": "Powitanie Nowego Klienta"
        }
    )
    frappe.msgprint("Rozmowa powitalna zainicjowana")
```

Będzie się uruchamiać za każdym razem gdy tworzysz nowego Customer.

---

## Troubleshooting

### "Cannot find customer KLIENT-001"

```python
# Sprawdź czy customer istnieje
frappe.get_doc("Customer", "KLIENT-001")  # Throws jeśli nie ma
```

### "Scenario jest nieaktywny"

```python
# W Call Scenario ustaw `is_active = 1`
scenario = frappe.get_doc("Call Scenario", "Dokumenty")
scenario.is_active = 1
scenario.save()
```

### "Brak numeru telefonu"

```python
# Customer musi mieć pole mobile_no lub phone uzupełnione
customer = frappe.get_doc("Customer", "KLIENT-001")
customer.mobile_no = "+48501234567"
customer.save()
```

### "Voice opt-out"

```python
# Odblokowywanie klienta
frappe.db.set_value("Customer", "KLIENT-001", "voice_opt_out", 0)
```

---

## Następnie

- Przejdź do **INSTALACJA.md** — jeśli jeszcze nie zainstalowałeś
- Przejdź do **SCENARIUSZE.md** — jak pisać dialogu
