from datetime import UTC, date, datetime

from app.models import Direction, DocumentStatus
from app.synchronization import (
    eot_document_refs,
    internal_status,
    parse_event_datetime,
    request_status,
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
