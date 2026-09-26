from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from app.schemas import (
    CustomerInput,
    DocumentFormCreate,
    DocumentOut,
    InvoiceFormCreate,
    OrganizationCreate,
)


def invoice_data(document_number: str) -> dict:
    return {
        "provider": "sef",
        "document_number": document_number,
        "issue_date": "2026-09-25",
        "due_date": "2026-10-10",
        "delivery_date": "2026-09-25",
        "currency": "RSD",
        "customer": {
            "name": "Test kupac",
            "tax_id": "123456789",
            "registration_number": "12345678",
            "address": {
                "street": "Test ulica 1",
                "city": "Subotica",
                "postal_code": "24000",
                "country_code": "RS",
            },
        },
        "lines": [
            {
                "name": "Usluga",
                "quantity": 1,
                "unit_code": "H87",
                "unit_price": 100,
                "vat_rate": 20,
                "vat_category": "S",
            }
        ],
    }


def despatch_data() -> dict:
    return {
        "provider": "eotpremnice",
        "document_number": "OT-1/2026",
        "issue_date": "2026-09-25",
        "customer": invoice_data("FA-1")["customer"],
        "shipment_id": "POS-1",
        "shipment_method": "2",
        "planned_despatch_at": "2026-09-25T08:00:00+02:00",
        "actual_despatch_at": "2026-09-25T08:10:00+02:00",
        "planned_delivery_at": "2026-09-25T12:00:00+02:00",
        "despatch_address": {
            "street": "Magacin 1",
            "city": "Subotica",
            "postal_code": "24000",
            "country_code": "RS",
        },
        "delivery_address": {
            "street": "Odredište 2",
            "city": "Novi Sad",
            "postal_code": "21000",
            "country_code": "RS",
        },
        "lines": [{"name": "Roba", "quantity": 1, "unit_code": "H87"}],
    }


@pytest.mark.parametrize("tax_id", ["12345678", "1234567890", "12345678A"])
def test_organization_requires_nine_digit_pib(tax_id: str):
    with pytest.raises(ValidationError):
        OrganizationCreate(name="Test firma", tax_id=tax_id)


@pytest.mark.parametrize("registration_number", ["1234567", "123456789", "1234567A"])
def test_customer_rejects_invalid_registration_number(registration_number: str):
    with pytest.raises(ValidationError):
        CustomerInput(
            name="Test kupac",
            tax_id="123456789",
            registration_number=registration_number,
            street="Test ulica 1",
            city="Subotica",
            postal_code="24000",
        )


def test_document_number_requires_at_least_three_visible_characters():
    with pytest.raises(ValidationError):
        InvoiceFormCreate(**invoice_data("AB"))
    with pytest.raises(ValidationError):
        InvoiceFormCreate(**invoice_data(" A "))

    document = InvoiceFormCreate(**invoice_data("  FA-1  "))
    assert document.document_number == "FA-1"


def test_document_output_keeps_legacy_short_document_numbers_visible():
    now = datetime.now(UTC)
    document = DocumentOut(
        id=uuid4(),
        provider="sef",
        direction="outbound",
        document_type="sales_invoice",
        document_number="2",
        idempotency_key="legacy-2",
        status="draft",
        remote_status=None,
        remote_status_at=None,
        external_id=None,
        last_error=None,
        created_at=now,
        updated_at=now,
    )

    assert document.document_number == "2"


def test_document_form_uses_provider_discriminator_and_clear_carrier_error():
    with pytest.raises(ValidationError) as error:
        TypeAdapter(DocumentFormCreate).validate_python(despatch_data())

    errors = error.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("eotpremnice",)
    assert "Naziv, PIB i matični broj prevoznika obavezni su" in errors[0]["msg"]


def test_despatch_rejects_actual_despatch_before_issue_date():
    payload = despatch_data()
    payload.update(
        {
            "issue_date": "2026-09-26",
            "actual_despatch_at": "2026-09-25T23:00:00+02:00",
            "carrier_name": "Prevoz DOO",
            "carrier_tax_id": "111222333",
            "carrier_registration_number": "12345678",
        }
    )

    with pytest.raises(ValidationError, match="Stvarni datum otpreme ne može biti pre"):
        TypeAdapter(DocumentFormCreate).validate_python(payload)
