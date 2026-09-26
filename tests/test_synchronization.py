from datetime import UTC, date, datetime
from decimal import Decimal

from app.models import Direction, DocumentStatus
from app.synchronization import (
    eot_document_refs,
    internal_status,
    parse_event_datetime,
    parse_sef_invoice_xml,
    request_status,
    sef_event_value,
    sef_sync_date,
)


def test_parse_event_datetime_supports_offset_and_invalid_values():
    parsed = parse_event_datetime("2026-09-23T10:11:12+02:00")
    assert parsed is not None
    assert parsed.astimezone(UTC).hour == 8
    assert parse_event_datetime("not-a-date") is None
    assert parse_event_datetime(None) is None


def test_eot_customer_event_maps_document_directions():
    event = {
        "data": {
            "despatchAdvice": {
                "id": "despatch-1",
                "documentNumber": "OT-1",
                "status": "Delivered",
            },
            "receiptAdvice": {
                "id": "receipt-1",
                "documentNumber": "PR-1",
                "status": "Sent",
            },
        }
    }
    refs = eot_document_refs("customers", event)
    assert refs[0]["direction"] == Direction.inbound
    assert refs[1]["direction"] == Direction.outbound
    assert refs[0]["external_id"] == "despatch-1"


def test_remote_status_mapping_preserves_business_meaning():
    assert internal_status("Approved") == DocumentStatus.accepted
    assert internal_status("Rejected") == DocumentStatus.rejected
    assert internal_status("Storno") == DocumentStatus.cancelled
    assert internal_status("Mistake") == DocumentStatus.error
    assert internal_status("Received") == DocumentStatus.delivered


def test_failed_async_request_is_not_downgraded_by_late_pending_event():
    assert request_status("Failed", "Pending") == "Failed"
    assert request_status("Pending", "Failed") == "Failed"


def test_sef_sync_date_is_always_in_the_past_and_recovers_future_cursor():
    today = date(2026, 9, 24)
    assert sef_sync_date(None, today=today, initial_lookback_days=1) == date(2026, 9, 23)
    future = datetime(2026, 9, 25, 12, tzinfo=UTC)
    assert sef_sync_date(future, today=today, initial_lookback_days=1) == date(2026, 9, 23)


def test_sef_initial_lookback_is_limited_to_retention_window():
    assert sef_sync_date(
        None, today=date(2026, 9, 24), initial_lookback_days=90
    ) == date(2026, 8, 25)


def test_sef_event_fields_support_live_pascal_case_and_documented_camel_case():
    live_event = {
        "EventId": 13959255,
        "PurchaseInvoiceId": 5644067,
        "NewInvoiceStatus": "New",
    }
    documented_event = {"eventId": 7, "purchaseInvoiceId": 8}

    assert sef_event_value(live_event, "eventId") == 13959255
    assert sef_event_value(live_event, "purchaseInvoiceId") == 5644067
    assert sef_event_value(live_event, "newInvoiceStatus") == "New"
    assert sef_event_value(documented_event, "eventId") == 7


def test_purchase_invoice_xml_summary_contains_supplier_and_amount():
    xml = b"""<?xml version="1.0" encoding="utf-8"?>
    <Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
      xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
      xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
      <cbc:ID>UL-2026-001</cbc:ID>
      <cbc:IssueDate>2026-09-25</cbc:IssueDate>
      <cbc:DocumentCurrencyCode>RSD</cbc:DocumentCurrencyCode>
      <cac:AccountingSupplierParty><cac:Party>
        <cac:PartyName><cbc:Name>Dobavljac DOO</cbc:Name></cac:PartyName>
        <cac:PartyTaxScheme><cbc:CompanyID>RS109876543</cbc:CompanyID></cac:PartyTaxScheme>
        <cac:PartyLegalEntity>
          <cbc:RegistrationName>Dobavljac DOO</cbc:RegistrationName>
        </cac:PartyLegalEntity>
      </cac:Party></cac:AccountingSupplierParty>
      <cac:LegalMonetaryTotal>
        <cbc:PayableAmount currencyID="RSD">1234.56</cbc:PayableAmount>
      </cac:LegalMonetaryTotal>
    </Invoice>"""

    result = parse_sef_invoice_xml(xml, "purchase")

    assert result["document_number"] == "UL-2026-001"
    assert result["issue_date"] == datetime(2026, 9, 24, 22, tzinfo=UTC)
    assert result["counterparty_name"] == "Dobavljac DOO"
    assert result["counterparty_tax_id"] == "109876543"
    assert result["currency"] == "RSD"
    assert result["total_amount"] == Decimal("1234.56")


def test_purchase_invoice_xml_summary_unwraps_sef_document_envelope():
    xml = b"""<?xml version="1.0" encoding="utf-8"?>
    <env:DocumentEnvelope xmlns:env="urn:eFaktura:MinFinrs:envelop:schema"
      xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
      xmlns:inv="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">
      <env:DocumentHeader><env:PurchaseInvoiceId>42</env:PurchaseInvoiceId></env:DocumentHeader>
      <env:DocumentBody><inv:Invoice><cbc:ID>UL-42</cbc:ID></inv:Invoice></env:DocumentBody>
    </env:DocumentEnvelope>"""

    assert parse_sef_invoice_xml(xml, "purchase")["document_number"] == "UL-42"
