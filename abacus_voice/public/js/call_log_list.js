/**
 * abacus_voice — Call Log list view
 * Kolorowe statusy i czytelna prezentacja wyników rozmów.
 */

frappe.listview_settings["Call Log"] = {
    add_fields: ["status", "client_id", "scenario", "started_at", "extracted_data"],

    get_indicator(doc) {
        const map = {
            "initiated":   ["Inicjowane", "blue"],
            "active":      ["Aktywna",    "blue"],
            "completed":   ["Zakończona", "green"],
            "unanswered":  ["Nieodebrana","orange"],
            "failed":      ["Błąd",       "red"],
            "opt-out":     ["Opt-out",    "gray"],
            "cancelled":   ["Anulowana",  "gray"],
        };
        return map[doc.status] || [doc.status, "gray"];
    },

    formatters: {
        extracted_data(value) {
            if (!value) return "";
            try {
                const data = JSON.parse(value);
                const result = data.result;
                const deadline = data.deadline;
                if (result === "TAK") return `<span class="badge badge-success">TAK</span>`;
                if (result === "NIE" && deadline) {
                    return `<span class="badge badge-warning">NIE — do: ${deadline}</span>`;
                }
                if (result === "NIE") return `<span class="badge badge-warning">NIE</span>`;
                return value;
            } catch {
                return value;
            }
        }
    }
};
