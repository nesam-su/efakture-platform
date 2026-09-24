import httpx

from app.integrations.http import GovernmentApiError
from app.worker import PermanentJobError, _error_message, _is_transient, _response_external_id


def test_response_external_id_supports_known_provider_shapes():
    assert _response_external_id({"invoiceId": 42}) == "42"
    assert _response_external_id({"documentId": "abc"}) == "abc"
    assert _response_external_id("accepted") is None


def test_retry_classification_is_conservative():
    request = httpx.Request("POST", "https://service.test")
    assert _is_transient(httpx.ConnectError("offline", request=request))
    assert _is_transient(GovernmentApiError("busy", status_code=503))
    assert _is_transient(GovernmentApiError("limited", status_code=429))
    assert not _is_transient(GovernmentApiError("invalid", status_code=400))
    assert not _is_transient(PermanentJobError("configuration missing"))


def test_government_error_message_includes_validator_body():
    error = GovernmentApiError(
        "Državni servis je vratio HTTP 400",
        status_code=400,
        body={"errors": ["SenderCompanyNotFound"]},
    )
    assert _error_message(error) == (
        'Državni servis je vratio HTTP 400: {"errors":["SenderCompanyNotFound"]}'
    )
