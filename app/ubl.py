from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from xml.etree import ElementTree as ET

from app.models import Organization
from app.schemas import (
    AddressInput,
    DespatchFormCreate,
    DocumentLineInput,
    InvoiceFormCreate,
    OrganizationProfileUpdate,
    PartyInput,
)

CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
CEC = "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2"
SBT = "http://mfin.gov.rs/srbdt/srbdtext"
INVOICE = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
DESPATCH = "urn:oasis:names:specification:ubl:schema:xsd:DespatchAdvice-2"

for prefix, namespace in (("cbc", CBC), ("cac", CAC), ("cec", CEC), ("sbt", SBT)):
    ET.register_namespace(prefix, namespace)

MONEY = Decimal("0.01")


def _element(parent: ET.Element, namespace: str, name: str, value=None, **attributes) -> ET.Element:
    element = ET.SubElement(parent, f"{{{namespace}}}{name}", attributes)
    if value is not None:
        element.text = str(value)
    return element


def _money(value: Decimal) -> str:
    return format(value.quantize(MONEY, rounding=ROUND_HALF_UP), "f")


def _date_and_time(parent: ET.Element, prefix: str, value) -> None:
    _element(parent, CBC, f"{prefix}Date", value.date().isoformat())
    _element(parent, CBC, f"{prefix}Time", value.timetz().isoformat())


def _address(parent: ET.Element, address: AddressInput, *, tag: str = "PostalAddress") -> None:
    node = _element(parent, CAC, tag)
    _element(node, CBC, "StreetName", address.street)
    _element(node, CBC, "CityName", address.city)
    _element(node, CBC, "PostalZone", address.postal_code)
    country = _element(node, CAC, "Country")
    _element(country, CBC, "IdentificationCode", address.country_code.upper())


def _party(
    parent: ET.Element, party: PartyInput, *, wrapper: str, nested_party: bool = True
) -> None:
    wrapper_node = _element(parent, CAC, wrapper)
    node = _element(wrapper_node, CAC, "Party") if nested_party else wrapper_node
    _element(node, CBC, "EndpointID", party.tax_id, schemeID="9948")
    if party.jbkjs:
        identification = _element(node, CAC, "PartyIdentification")
        _element(identification, CBC, "ID", f"JBKJS:{party.jbkjs}")
    party_name = _element(node, CAC, "PartyName")
    _element(party_name, CBC, "Name", party.name)
    _address(node, party.address)
    tax_scheme = _element(node, CAC, "PartyTaxScheme")
    _element(tax_scheme, CBC, "CompanyID", f"RS{party.tax_id}")
    scheme = _element(tax_scheme, CAC, "TaxScheme")
    _element(scheme, CBC, "ID", "VAT")
    legal = _element(node, CAC, "PartyLegalEntity")
    _element(legal, CBC, "RegistrationName", party.name)
    if party.registration_number:
        _element(legal, CBC, "CompanyID", party.registration_number)
    if party.email:
        contact = _element(node, CAC, "Contact")
        _element(contact, CBC, "ElectronicMail", party.email)


def organization_party(organization: Organization) -> tuple[PartyInput, OrganizationProfileUpdate]:
    profile = OrganizationProfileUpdate.model_validate(
        {
            **organization.profile,
            "name": organization.name,
            "tax_id": organization.tax_id,
            "registration_number": organization.registration_number,
        }
    )
    party = PartyInput(
        name=organization.name,
        tax_id=organization.tax_id,
        registration_number=organization.registration_number,
        email=profile.email,
        jbkjs=profile.jbkjs,
        address=AddressInput(
            street=profile.street,
            city=profile.city,
            postal_code=profile.postal_code,
            country_code=profile.country_code,
        ),
    )
    return party, profile


def invoice_totals(data: InvoiceFormCreate) -> tuple[Decimal, Decimal, Decimal]:
    net = Decimal("0")
    tax = Decimal("0")
    for line in data.lines:
        line_net = line.quantity * (line.unit_price or Decimal("0"))
        net += line_net
        tax += line_net * (line.vat_rate or Decimal("0")) / Decimal("100")
    net = net.quantize(MONEY, rounding=ROUND_HALF_UP)
    tax = tax.quantize(MONEY, rounding=ROUND_HALF_UP)
    return net, tax, net + tax


def _invoice_line(root: ET.Element, line: DocumentLineInput, index: int, currency: str) -> None:
    node = _element(root, CAC, "InvoiceLine")
    _element(node, CBC, "ID", index)
    _element(node, CBC, "InvoicedQuantity", line.quantity, unitCode=line.unit_code)
    line_net = line.quantity * (line.unit_price or Decimal("0"))
    _element(node, CBC, "LineExtensionAmount", _money(line_net), currencyID=currency)
    item = _element(node, CAC, "Item")
    if line.description:
        _element(item, CBC, "Description", line.description)
    _element(item, CBC, "Name", line.name)
    if line.seller_item_id:
        identification = _element(item, CAC, "SellersItemIdentification")
        _element(identification, CBC, "ID", line.seller_item_id)
    category = _element(item, CAC, "ClassifiedTaxCategory")
    _element(category, CBC, "ID", line.vat_category)
    _element(category, CBC, "Percent", line.vat_rate or 0)
    if line.exemption_reason_code:
        _element(category, CBC, "TaxExemptionReasonCode", line.exemption_reason_code)
    scheme = _element(category, CAC, "TaxScheme")
    _element(scheme, CBC, "ID", "VAT")
    price = _element(node, CAC, "Price")
    _element(
        price,
        CBC,
        "PriceAmount",
        _money(line.unit_price or Decimal("0")),
        currencyID=currency,
    )


def generate_invoice_xml(organization: Organization, data: InvoiceFormCreate) -> bytes:
    supplier, profile = organization_party(organization)
    ET.register_namespace("", INVOICE)
    root = ET.Element(f"{{{INVOICE}}}Invoice")
    _element(
        root,
        CBC,
        "CustomizationID",
        "urn:cen.eu:en16931:2017#compliant#urn:mfin.gov.rs:srbdt:2022",
    )
    _element(root, CBC, "ID", data.document_number)
    _element(root, CBC, "IssueDate", data.issue_date.isoformat())
    _element(root, CBC, "DueDate", data.due_date.isoformat())
    _element(root, CBC, "InvoiceTypeCode", "380")
    if data.note:
        _element(root, CBC, "Note", data.note)
    _element(root, CBC, "DocumentCurrencyCode", data.currency.upper())
    invoice_period = _element(root, CAC, "InvoicePeriod")
    _element(invoice_period, CBC, "DescriptionCode", "35")
    _party(root, supplier, wrapper="AccountingSupplierParty")
    _party(root, data.customer, wrapper="AccountingCustomerParty")
    delivery = _element(root, CAC, "Delivery")
    _element(delivery, CBC, "ActualDeliveryDate", data.delivery_date.isoformat())
    account = data.payment_account or profile.bank_account
    if account:
        payment = _element(root, CAC, "PaymentMeans")
        _element(payment, CBC, "PaymentMeansCode", "30")
        if data.payment_reference:
            _element(payment, CBC, "PaymentID", data.payment_reference)
        financial = _element(payment, CAC, "PayeeFinancialAccount")
        _element(financial, CBC, "ID", account)

    groups: dict[tuple[str, Decimal, str | None], list[Decimal]] = defaultdict(
        lambda: [Decimal("0"), Decimal("0")]
    )
    for line in data.lines:
        line_net = line.quantity * (line.unit_price or Decimal("0"))
        rate = line.vat_rate or Decimal("0")
        key = (line.vat_category, rate, line.exemption_reason_code)
        groups[key][0] += line_net
        groups[key][1] += line_net * rate / Decimal("100")
    net, tax, payable = invoice_totals(data)
    tax_total = _element(root, CAC, "TaxTotal")
    _element(tax_total, CBC, "TaxAmount", _money(tax), currencyID=data.currency.upper())
    for (category_id, rate, exemption), (taxable, category_tax) in groups.items():
        subtotal = _element(tax_total, CAC, "TaxSubtotal")
        _element(subtotal, CBC, "TaxableAmount", _money(taxable), currencyID=data.currency.upper())
        _element(subtotal, CBC, "TaxAmount", _money(category_tax), currencyID=data.currency.upper())
        category = _element(subtotal, CAC, "TaxCategory")
        _element(category, CBC, "ID", category_id)
        _element(category, CBC, "Percent", rate)
        if exemption:
            _element(category, CBC, "TaxExemptionReasonCode", exemption)
        scheme = _element(category, CAC, "TaxScheme")
        _element(scheme, CBC, "ID", "VAT")
    totals = _element(root, CAC, "LegalMonetaryTotal")
    for name, value in (
        ("LineExtensionAmount", net),
        ("TaxExclusiveAmount", net),
        ("TaxInclusiveAmount", payable),
        ("PayableAmount", payable),
    ):
        _element(totals, CBC, name, _money(value), currencyID=data.currency.upper())
    for index, line in enumerate(data.lines, 1):
        _invoice_line(root, line, index, data.currency.upper())
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _despatch_line(root: ET.Element, line: DocumentLineInput, index: int) -> None:
    node = _element(root, CAC, "DespatchLine")
    _element(node, CBC, "ID", index)
    _element(node, CBC, "DeliveredQuantity", line.quantity, unitCode=line.unit_code)
    reference = _element(node, CAC, "OrderLineReference")
    _element(reference, CBC, "LineID", index)
    item = _element(node, CAC, "Item")
    if line.description:
        _element(item, CBC, "Description", line.description)
    _element(item, CBC, "Name", line.name)
    if line.seller_item_id:
        identification = _element(item, CAC, "SellersItemIdentification")
        _element(identification, CBC, "ID", line.seller_item_id)
    if line.gtin:
        identification = _element(item, CAC, "StandardItemIdentification")
        _element(identification, CBC, "ID", line.gtin)


def generate_despatch_xml(organization: Organization, data: DespatchFormCreate) -> bytes:
    supplier, _ = organization_party(organization)
    ET.register_namespace("", DESPATCH)
    root = ET.Element(f"{{{DESPATCH}}}DespatchAdvice")
    extensions = _element(root, CEC, "UBLExtensions")
    extension = _element(extensions, CEC, "UBLExtension")
    content = _element(extension, CEC, "ExtensionContent")
    srbdt = _element(content, SBT, "SrbDtExt")
    method = _element(srbdt, SBT, "ShipmentMethod")
    _element(method, CBC, "ShipmentMethodType", data.shipment_method)
    _element(
        root,
        CBC,
        "CustomizationID",
        "urn:fdc:mfin.gov.rs:logistics:trns:despatch_advice:1:2025.12",
    )
    _element(root, CBC, "ProfileID", "urn:fdc:peppol.eu:logistics:bis:despatch_advice_only:1")
    _element(root, CBC, "ID", data.document_number)
    _element(root, CBC, "IssueDate", data.issue_date.isoformat())
    _element(root, CBC, "DespatchAdviceTypeCode", data.despatch_type)
    if data.note:
        _element(root, CBC, "Note", data.note)
    if data.order_reference:
        reference = _element(root, CAC, "OrderReference")
        _element(reference, CBC, "ID", data.order_reference)
    _party(root, supplier, wrapper="DespatchSupplierParty")
    _party(root, data.customer, wrapper="DeliveryCustomerParty")
    shipment = _element(root, CAC, "Shipment")
    _element(shipment, CBC, "ID", data.shipment_id)
    if data.gross_weight is not None:
        _element(shipment, CBC, "GrossWeightMeasure", data.gross_weight, unitCode="KGM")
    if data.package_count is not None:
        _element(shipment, CBC, "TotalTransportHandlingUnitQuantity", data.package_count)
    if any((data.carrier_name, data.carrier_tax_id, data.vehicle_plate, data.driver_email)):
        stage = _element(shipment, CAC, "ShipmentStage")
        _element(stage, CBC, "ID", "1")
        if data.carrier_name and data.carrier_tax_id:
            carrier = PartyInput(
                name=data.carrier_name,
                tax_id=data.carrier_tax_id,
                registration_number=data.carrier_registration_number,
                address=data.despatch_address,
            )
            _party(stage, carrier, wrapper="CarrierParty", nested_party=False)
        if data.vehicle_plate:
            means = _element(stage, CAC, "TransportMeans")
            road = _element(means, CAC, "RoadTransport")
            _element(road, CBC, "LicensePlateID", data.vehicle_plate)
        if data.driver_email:
            driver = _element(stage, CAC, "DriverPerson")
            _element(driver, CBC, "ID", data.driver_email)
            if data.driver_name:
                parts = data.driver_name.strip().split(" ", 1)
                _element(driver, CBC, "FirstName", parts[0])
                if len(parts) > 1:
                    _element(driver, CBC, "FamilyName", parts[1])
    delivery = _element(shipment, CAC, "Delivery")
    _address(delivery, data.delivery_address, tag="DeliveryAddress")
    period = _element(delivery, CAC, "EstimatedDeliveryPeriod")
    _date_and_time(period, "End", data.planned_delivery_at)
    despatch = _element(delivery, CAC, "Despatch")
    _date_and_time(despatch, "EstimatedDespatch", data.planned_despatch_at)
    _date_and_time(despatch, "ActualDespatch", data.actual_despatch_at)
    _address(despatch, data.despatch_address, tag="DespatchAddress")
    for index, line in enumerate(data.lines, 1):
        _despatch_line(root, line, index)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
