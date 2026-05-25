/**
 * abacus_voice — rozszerzenie formularza Customer
 * Dodaje przycisk "Zadzwoń" który otwiera dialog wyboru scenariusza.
 */

frappe.ui.form.on("Customer", {
    refresh(frm) {
        // Nie pokazuj przycisku dla nowych, niezapisanych rekordów
        if (frm.is_new()) return;

        frm.add_custom_button(__("Zadzwoń"), function () {
            _open_call_dialog(frm);
        }, __("Abacus Voice"));

        // Jeśli klient ma opt-out — pokaż ostrzeżenie
        if (frm.doc.voice_opt_out) {
            frm.dashboard.add_comment(
                __("Ten klient jest wypisany z kontaktu automatycznego (voice_opt_out). " +
                   "Odznacz pole 'Wypisany z kontaktu automatycznego' aby włączyć rozmowy automatyczne."),
                "orange",
                true
            );
        }
    }
});


function _open_call_dialog(frm) {
    // Pobierz listę aktywnych scenariuszy
    frappe.call({
        method: "frappe.client.get_list",
        args: {
            doctype: "Call Scenario",
            filters: { is_active: 1 },
            fields: ["name", "title"],
            limit: 50,
        },
        callback(r) {
            if (!r.message || r.message.length === 0) {
                frappe.msgprint({
                    title: __("Brak scenariuszy"),
                    message: __("Nie ma aktywnych scenariuszy rozmów. Utwórz scenariusz w Call Scenario."),
                    indicator: "orange",
                });
                return;
            }

            const scenario_options = r.message.map(s => ({
                label: s.title || s.name,
                value: s.name,
            }));

            _show_call_dialog(frm, scenario_options);
        }
    });
}


function _show_call_dialog(frm, scenario_options) {
    const dialog = new frappe.ui.Dialog({
        title: __("Zadzwoń do klienta"),
        fields: [
            {
                fieldname: "info",
                fieldtype: "HTML",
                options: `<div class="alert alert-info">
                    <strong>${frm.doc.customer_name}</strong><br>
                    Numer: <strong>${frm.doc.mobile_no || frm.doc.phone || __("(brak numeru)")}</strong>
                </div>`
            },
            {
                fieldname: "scenario_id",
                fieldtype: "Select",
                label: __("Scenariusz rozmowy"),
                options: scenario_options.map(s => s.value).join("\n"),
                reqd: 1,
                description: __("Wybierz scenariusz który system ma przeprowadzić z klientem."),
            },
            {
                fieldname: "context_section",
                fieldtype: "Section Break",
                label: __("Dane dodatkowe (opcjonalne)"),
                collapsible: 1,
            },
            {
                fieldname: "context_data",
                fieldtype: "Code",
                label: __("Context Data (JSON)"),
                options: "JSON",
                description: __(
                    "Opcjonalne dane do wstrzyknięcia do scenariusza jako zmienne Jinja2. " +
                    'Przykład: {"kwota": "1500", "termin": "31 maja"}'
                ),
            },
        ],
        primary_action_label: __("Zadzwoń"),
        primary_action(values) {
            if (!values.scenario_id) {
                frappe.msgprint(__("Wybierz scenariusz rozmowy."));
                return;
            }

            // Walidacja context_data jeśli podane
            if (values.context_data && values.context_data.trim()) {
                try {
                    JSON.parse(values.context_data);
                } catch (e) {
                    frappe.msgprint({
                        title: __("Nieprawidłowy JSON"),
                        message: __("Context Data musi być prawidłowym JSON. Sprawdź format."),
                        indicator: "red",
                    });
                    return;
                }
            }

            dialog.hide();
            _initiate_call(frm, values.scenario_id, values.context_data || null);
        }
    });

    // Ustaw domyślnie pierwszy scenariusz
    if (scenario_options.length > 0) {
        dialog.set_value("scenario_id", scenario_options[0].value);
    }

    dialog.show();
}


function _initiate_call(frm, scenario_id, context_data) {
    frappe.show_progress(__("Inicjowanie połączenia"), 50, 100, __("Łączę z Vonage..."));

    frappe.call({
        method: "abacus_voice.api.initiate_call",
        args: {
            client_id: frm.doc.name,
            scenario_id: scenario_id,
            context_data: context_data,
        },
        callback(r) {
            frappe.hide_progress();

            if (r.exc) {
                // Błąd — frappe.call automatycznie pokazuje wyjątek
                return;
            }

            const uuid = r.message && r.message.conversation_uuid;
            frappe.msgprint({
                title: __("Połączenie zainicjowane"),
                message: __(
                    "System dzwoni do klienta. Wyniki rozmowy pojawią się w historii połączeń." +
                    (uuid ? `<br><small>UUID: ${uuid}</small>` : "")
                ),
                indicator: "green",
            });

            // Odśwież formularz żeby pokazać nowy CallLog
            frm.reload_doc();
        },
        error(r) {
            frappe.hide_progress();
        }
    });
}
