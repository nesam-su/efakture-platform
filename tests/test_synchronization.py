from datetime import UTC

from app.models import Direction, DocumentStatus
from app.synchronization import eot_document_refs, internal_status, parse_event_datetime


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
