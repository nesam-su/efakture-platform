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
    assert '/static/app.js?v=0.8.19' in template


def test_frontend_separates_inbound_and_outbound_invoices_in_sidebar():
    script = (PROJECT_ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    template = (PROJECT_ROOT / "app" / "templates" / "index.html").read_text(
        encoding="utf-8"
    )

    assert 'data-document-scope="inbound"' in template
    assert 'data-document-scope="outbound"' in template
    assert 'data-document-scope="despatch"' in template
    assert "Ulazne fakture" in template
    assert "Izlazne fakture" in template
    assert "Otpremnice" in template
    assert '>Dokumenti</button>' not in template
    assert 'doc.document_type === "purchase_invoice"' in script
    assert 'doc.document_type === "sales_invoice"' in script
    assert 'showDocumentScope(button.dataset.documentScope)' in script
    assert 'data-print-document-id="${doc.id}">Štampaj</button>' in script
    assert "XML je namenjen razmeni sa državnim servisom" in script
    assert 'new:"Novo"' in script
    assert 'return "Primljena"' in script
    assert 'return "Poslata"' in script


def test_print_layout_has_professional_invoice_sections():
    script = (PROJECT_ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")

    print_styles = (PROJECT_ROOT / "app" / "static" / "print.css").read_text(
        encoding="utf-8"
    )

    assert '@page { size: A4' in print_styles
    assert 'class="document-header"' in script
    assert 'class="parties"' in script
    assert 'Pregled PDV-a' in script
    assert 'UKUPNO ZA PLAĆANJE' in script
    assert 'Podaci za plaćanje' in script
    assert 'print-color-adjust: exact' in print_styles
    assert 'thead { display: table-header-group; }' in print_styles
    assert '/static/print.css?v=0.8.19' in script
    assert (
        ".party:first-child { border-right: 0; border-bottom: 0; border-left: 0; }"
        in print_styles
    )
    assert 'id="print-detail"' not in script
    assert 'showPrintPreview(button.dataset.printDocumentId)' in script
    assert 'function printDocument(doc, preview, existingPopup = null)' in script
    assert 'class="print-toolbar"' in script
    assert 'id="print-now"' in script
    assert 'Štampaj dokument' in script
    assert 'setTimeout(() => popup.print()' not in script


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
    assert 'issueDate.readOnly = !invoice' in script
    assert 'planned.min = minimum; actual.min = minimum' in script
    assert 'delivery.min = [minimum, planned.value, actual.value]' in script
    assert 'Datum izdavanja je današnji datum Srbije' in script


def test_new_document_follows_active_scope_and_reveals_saved_document():
    script = (PROJECT_ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")

    assert 'state.documentScope === "despatch" ? "eotpremnice" : "sef"' in script
    assert (
        'state.documentScope = provider === "eotpremnice" ? "despatch" : "outbound"'
        in script
    )
    assert 'sessionStorage.setItem(documentScopeKey, state.documentScope)' in script
    assert '$("#document-search").value = ""; $("#status-filter").value = "";' in script


def test_document_lists_do_not_show_redundant_service_column():
    script = (PROJECT_ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    template = (PROJECT_ROOT / "app" / "templates" / "index.html").read_text(
        encoding="utf-8"
    )

    assert "<th>Servis</th>" not in template
    assert 'id="provider-filter"' not in template
    assert 'class="service ${doc.provider}"' not in script
