app_name = "abacus_voice"
app_title = "Abacus Voice"
app_publisher = "Abacus Centrum Księgowe"
app_description = "Moduł automatycznych rozmów telefonicznych"
app_email = "kontakt@abacus24.pl"
app_license = "MIT"

# DocType JS — custom buttons i list views
doctype_js = {
    "Customer": "public/js/customer.js",
}

doctype_list_js = {
    "Call Queue": "public/js/call_queue_list.js",
    "Call Log":   "public/js/call_log_list.js",
}

# Scheduler — retry queue co 15 minut
scheduler_events = {
    "cron": {
        "*/15 * * * *": [
            "abacus_voice.scheduler.process_call_queue"
        ]
    }
}

# Fixtures — eksportuj custom fields przy bench export-fixtures
fixtures = [
    {"dt": "Custom Field", "filters": [["dt", "in", ["Customer"]]]},
]
