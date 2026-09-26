from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_frontend_uses_five_second_safe_auto_refresh():
    script = (PROJECT_ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")

    assert "const autoRefreshIntervalMs = 5000" in script
    assert 'document.querySelector("dialog[open]")' in script
    assert "setInterval(autoRefreshActiveView, autoRefreshIntervalMs)" in script


def test_frontend_uses_provider_specific_send_labels():
    script = (PROJECT_ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    template = (PROJECT_ROOT / "app" / "templates" / "index.html").read_text(
        encoding="utf-8"
    )

    assert 'return provider === "sef" ? "SEF" : "eOtpremnice"' in script
    assert "Pošalji u red" not in script
    assert "Pošalji u red" not in template
    assert '/static/app.js?v=0.8.7' in template


def test_carrier_fields_are_required_for_external_carrier_transport():
    script = (PROJECT_ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")

    assert 'form.elements.shipment_method.value === "2"' in script
    assert '["carrier_name", "carrier_tax_id", "carrier_registration_number"]' in script
    assert 'addEventListener("change", toggleCarrierRequirements)' in script
    assert 'replace(/^Value error,\\s*/i, "")' in script


def test_existing_despatch_editor_uses_current_serbian_issue_date():
    script = (PROJECT_ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")

    assert 'timeZone:"Europe/Belgrade"' in script
    assert 'form.elements.issue_date.value = serbianCalendarDate()' in script
