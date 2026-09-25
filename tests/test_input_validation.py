import pytest
from pydantic import ValidationError

from app.schemas import CustomerInput, InvoiceFormCreate, OrganizationCreate


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
