from datetime import date, datetime
from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest
from pydantic import ValidationError

from app.models import Organization
from app.schemas import (
    AddressInput,
    CatalogItemInput,
    DespatchFormCreate,
    DocumentLineInput,
    InvoiceFormCreate,
    PartyInput,
)
from app.ubl import CAC, CBC, generate_despatch_xml, generate_invoice_xml, invoice_totals


def organization() -> Organization:
    return Organization(
        name="Dobavljač & Sin",
        tax_id="123456789",
        registration_number="12345678",
        profile={
            "street": "Glavna 1",
            "city": "Subotica",
            "postal_code": "24000",
            "country_code": "RS",
            "email": "office@example.rs",
            "bank_account": "160-0000000000000-00",
            "phone": None,
            "jbkjs": None,
        },
    )


def customer() -> PartyInput:
    return PartyInput(
        name="Kupac DOO",
        tax_id="987654321",
        registration_number="87654321",
        email="kupac@example.rs",
        address=AddressInput(street="Druga 2", city="Novi Sad", postal_code="21000"),
    )


def test_party_rejects_invalid_serbian_identifier_length():
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        PartyInput(
            name="Neispravna firma",
            tax_id="12345678",
            address=AddressInput(street="Test 1", city="Subotica", postal_code="24000"),
        )


def test_catalog_item_accepts_simple_vat_choices():
    for rate, category in (("20", "S"), ("10", "S"), ("0", "Z"), ("0", "O")):
        item = CatalogItemInput(
            name="Test", sku=f"A-{rate}-{category}", vat_rate=rate, vat_category=category
        )
        assert item.vat_category == category


def test_catalog_item_rejects_invalid_standard_vat_rate():
    with pytest.raises(ValidationError, match="10% ili 20%"):
        CatalogItemInput(name="Test", sku="A-1", vat_rate="15", vat_category="S")


def test_invoice_form_generates_totals_and_valid_ubl_xml():
    data = InvoiceFormCreate(
        provider="sef",
        document_number="FA-1/2026",
        issue_date=date(2026, 9, 24),
        due_date=date(2026, 10, 4),
        delivery_date=date(2026, 9, 24),
        customer=customer(),
        lines=[
            DocumentLineInput(
                name="Usluga & materijal",
                quantity=Decimal("2"),
                unit_code="H87",
                unit_price=Decimal("100.00"),
                vat_rate=Decimal("20"),
            ),
            DocumentLineInput(
                name="Druga stavka",
                quantity=Decimal("1"),
                unit_code="H87",
                unit_price=Decimal("50.00"),
                vat_rate=Decimal("10"),
            ),
        ],
    )
    assert invoice_totals(data) == (Decimal("250.00"), Decimal("45.00"), Decimal("295.00"))
    root = ET.fromstring(generate_invoice_xml(organization(), data))
    assert root.findtext(f"{{{CBC}}}ID") == "FA-1/2026"
    assert root.findtext(f".//{{{CAC}}}AccountingSupplierParty//{{{CBC}}}Name") == (
        "Dobavljač & Sin"
    )
    assert root.findtext(f".//{{{CAC}}}LegalMonetaryTotal/{{{CBC}}}PayableAmount") == "295.00"
    assert len(root.findall(f"{{{CAC}}}InvoiceLine")) == 2


def test_despatch_form_generates_transport_and_lines():
    data = DespatchFormCreate(
        provider="eotpremnice",
        document_number="OT-1/2026",
        issue_date=date(2026, 9, 24),
        customer=customer(),
        shipment_id="POS-1",
        shipment_method="2",
        planned_despatch_at=datetime.fromisoformat("2026-09-25T08:00:00+02:00"),
        actual_despatch_at=datetime.fromisoformat("2026-09-25T08:10:00+02:00"),
        planned_delivery_at=datetime.fromisoformat("2026-09-25T12:00:00+02:00"),
        despatch_address=AddressInput(
            street="Magacin 1", city="Subotica", postal_code="24000"
        ),
        delivery_address=AddressInput(
            street="Odredište 2", city="Novi Sad", postal_code="21000"
        ),
        carrier_name="Prevoz DOO",
        carrier_tax_id="111222333",
        carrier_registration_number="12345678",
        vehicle_plate="SU-123-AA",
        driver_name="Petar Petrović",
        driver_email="vozac@example.rs",
        lines=[
            DocumentLineInput(
                name="Roba",
                seller_item_id="ART-1",
                quantity=Decimal("5"),
                unit_code="H87",
            )
        ],
    )
    root = ET.fromstring(generate_despatch_xml(organization(), data))
    assert root.findtext(f"{{{CBC}}}ID") == "OT-1/2026"
    assert root.findtext(f".//{{{CAC}}}RoadTransport/{{{CBC}}}LicensePlateID") == "SU-123-AA"
    assert root.findtext(f".//{{{CAC}}}DriverPerson/{{{CBC}}}ID") == "vozac@example.rs"
    assert root.findtext(f".//{{{CBC}}}ActualDespatchDate") == "2026-09-25"
    assert root.findtext(
        f".//{{{CAC}}}CarrierParty/{{{CAC}}}PartyLegalEntity/{{{CBC}}}CompanyID"
    ) == "12345678"
    assert len(root.findall(f"{{{CAC}}}DespatchLine")) == 1


def test_despatch_rejects_incomplete_carrier_details():
    with pytest.raises(ValidationError, match="Naziv, PIB i matični broj prevoznika"):
        DespatchFormCreate(
            provider="eotpremnice",
            document_number="OT-2/2026",
            issue_date=date(2026, 9, 24),
            customer=customer(),
            shipment_id="POS-2",
            shipment_method="2",
            planned_despatch_at=datetime.fromisoformat("2026-09-25T08:00:00+02:00"),
            actual_despatch_at=datetime.fromisoformat("2026-09-25T08:10:00+02:00"),
            planned_delivery_at=datetime.fromisoformat("2026-09-25T12:00:00+02:00"),
            despatch_address=AddressInput(
                street="Magacin 1", city="Subotica", postal_code="24000"
            ),
            delivery_address=AddressInput(
                street="Odredište 2", city="Novi Sad", postal_code="21000"
            ),
            carrier_name="Prevoz bez PIB-a",
            lines=[DocumentLineInput(name="Roba", quantity=Decimal("1"))],
        )
