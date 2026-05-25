/**
 * abacus_voice — Call Queue list view
 * Dodaje przycisk "Anuluj" dla rekordów ze statusem pending.
 */

frappe.listview_settings["Call Queue"] = {
    add_fields: ["status", "client_id", "scenario", "attempt_number", "scheduled_at"],

    get_indicator(doc) {
        const map = {
            "pending":     ["Oczekuje", "orange"],
            "in_progress": ["W trakcie", "blue"],
            "completed":   ["Zakończona", "green"],
            "cancelled":   ["Anulowana", "gray"],
            "exhausted":   ["Wyczerpana", "red"],
        };
        return map[doc.status] || [doc.status, "gray"];
    },

    button: {
        show(doc) {
            return doc.status === "pending";
        },
        get_label() {
            return __("Anuluj retry");
        },
        get_description(doc) {
            return __(`Anuluj zaplanowane połączenie do ${doc.client_id}`);
        },
        action(doc) {
            frappe.confirm(
                __(`Czy na pewno chcesz anulować retry dla klienta <b>${doc.client_id}</b>?`),
                () => {
                    frappe.call({
                        method: "abacus_voice.scheduler.cancel_queue_item",
                        args: { queue_name: doc.name },
                        callback(r) {
                            if (r.message && r.message.status === "cancelled") {
                                frappe.show_alert({
                                    message: __("Retry anulowany."),
                                    indicator: "green",
                                });
                                cur_list.refresh();
                            }
                        }
                    });
                }
            );
        }
    },

    onload(listview) {
        // Dodaj filtr "Tylko oczekujące" jako domyślny widok
        listview.filter_area.add([
            ["Call Queue", "status", "=", "pending"]
        ]);
    }
};
