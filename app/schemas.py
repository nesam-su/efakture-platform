from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, model_validator

from app.integrations.environments import IntegrationEnvironment
from app.models import Direction, DocumentStatus, JobStatus, Provider, Role


class BootstrapRequest(BaseModel):
    organization_name: str = Field(min_length=2, max_length=200)
    tax_id: str = Field(pattern=r"^(?:\d{9}|\d{13})$")
    registration_number: str | None = Field(default=None, max_length=30)
    admin_name: str = Field(min_length=2, max_length=200)
    admin_email: EmailStr
    password: SecretStr = Field(min_length=12, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: SecretStr
    mfa_code: str | None = Field(default=None, min_length=6, max_length=20)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=32, max_length=200)
    password: SecretStr = Field(min_length=12, max_length=200)
    confirm_password: SecretStr = Field(min_length=12, max_length=200)


class MessageResponse(BaseModel):
    message: str


class MfaSetupRequest(BaseModel):
    password: SecretStr


class MfaSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str


class MfaConfirmRequest(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class MfaRecoveryCodesResponse(BaseModel):
    recovery_codes: list[str]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AuthSessionOut(BaseModel):
    id: UUID
    current: bool
    ip_address: str | None
    user_agent: str | None
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    tax_id: str
    registration_number: str | None
    profile: dict = Field(default_factory=dict)
    role: Role | None = None


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    tax_id: str = Field(pattern=r"^(?:\d{9}|\d{13})$")
    registration_number: str | None = Field(default=None, max_length=30)


class OrganizationProfileUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    tax_id: str = Field(pattern=r"^(?:\d{9}|\d{13})$")
    registration_number: str | None = Field(default=None, max_length=30)
    street: str = Field(min_length=2, max_length=300)
    city: str = Field(min_length=2, max_length=120)
    postal_code: str = Field(min_length=2, max_length=20)
    country_code: str = Field(default="RS", min_length=2, max_length=2)
    email: EmailStr
    bank_account: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=50)
    jbkjs: str | None = Field(default=None, max_length=30)


class MembershipOut(BaseModel):
    id: UUID
    user_id: UUID
    email: EmailStr
    full_name: str
    role: Role
    is_active: bool


class InvitationCreate(BaseModel):
    email: EmailStr
    role: Role
    expires_in_hours: int = Field(default=72, ge=1, le=168)


class InvitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: EmailStr
    role: Role
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class InvitationIssued(InvitationOut):
    invitation_token: str


class InvitationAccept(BaseModel):
    invitation_token: str = Field(min_length=32, max_length=200)
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    password: SecretStr = Field(min_length=12, max_length=200)


class CredentialUpsert(BaseModel):
    provider: Provider
    environment: IntegrationEnvironment = "demo"
    api_key: SecretStr
    settings: dict = Field(default_factory=dict)


class CredentialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    provider: Provider
    base_url: str
    settings: dict
    is_active: bool


class DocumentCreate(BaseModel):
    provider: Provider
    direction: Direction
    document_type: str = Field(min_length=1, max_length=80)
    document_number: str | None = Field(default=None, max_length=100)
    idempotency_key: str = Field(min_length=8, max_length=128)
    issue_date: datetime | None = None
    counterparty_name: str | None = Field(default=None, max_length=300)
    counterparty_tax_id: str | None = Field(default=None, max_length=20)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    total_amount: Decimal | None = None
    payload: dict = Field(default_factory=dict)


class AddressInput(BaseModel):
    street: str = Field(min_length=2, max_length=300)
    city: str = Field(min_length=2, max_length=120)
    postal_code: str = Field(min_length=2, max_length=20)
    country_code: str = Field(default="RS", min_length=2, max_length=2)


class PartyInput(BaseModel):
    name: str = Field(min_length=2, max_length=300)
    tax_id: str = Field(pattern=r"^(?:\d{9}|\d{13})$")
    registration_number: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = None
    jbkjs: str | None = Field(default=None, max_length=30)
    address: AddressInput


class DocumentLineInput(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=1000)
    seller_item_id: str | None = Field(default=None, max_length=100)
    gtin: str | None = Field(default=None, max_length=30)
    quantity: Decimal = Field(gt=0, max_digits=20, decimal_places=6)
    unit_code: str = Field(default="H87", min_length=2, max_length=3)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=6)
    vat_rate: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)
    vat_category: str = Field(default="S", min_length=1, max_length=4)
    exemption_reason_code: str | None = Field(default=None, max_length=50)


class InvoiceFormCreate(BaseModel):
    provider: Literal["sef"]
    document_number: str = Field(min_length=1, max_length=100)
    issue_date: date
    due_date: date
    delivery_date: date
    currency: str = Field(default="RSD", min_length=3, max_length=3)
    customer: PartyInput
    payment_account: str | None = Field(default=None, max_length=80)
    payment_reference: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=2000)
    lines: list[DocumentLineInput] = Field(min_length=1, max_length=500)
    queue_after_create: bool = False

    @model_validator(mode="after")
    def validate_invoice(self):
        if self.due_date < self.issue_date:
            raise ValueError("Datum dospeća ne može biti pre datuma izdavanja")
        if any(line.unit_price is None or line.vat_rate is None for line in self.lines):
            raise ValueError("Cena i PDV stopa su obavezni za svaku stavku fakture")
        return self


class DespatchFormCreate(BaseModel):
    provider: Literal["eotpremnice"]
    document_number: str = Field(min_length=1, max_length=100)
    issue_date: date
    despatch_type: Literal["Ext", "Int"] = "Ext"
    order_reference: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=2000)
    customer: PartyInput
    shipment_id: str = Field(min_length=1, max_length=100)
    shipment_method: Literal["1", "2", "3", "4", "5"]
    planned_despatch_at: datetime
    actual_despatch_at: datetime
    planned_delivery_at: datetime
    despatch_address: AddressInput
    delivery_address: AddressInput
    gross_weight: Decimal | None = Field(default=None, gt=0, decimal_places=3)
    package_count: int | None = Field(default=None, gt=0)
    carrier_name: str | None = Field(default=None, max_length=300)
    carrier_tax_id: str | None = Field(default=None, pattern=r"^(?:\d{9}|\d{13})$")
    carrier_registration_number: str | None = Field(default=None, max_length=30)
    vehicle_plate: str | None = Field(default=None, max_length=30)
    driver_name: str | None = Field(default=None, max_length=200)
    driver_email: EmailStr | None = None
    lines: list[DocumentLineInput] = Field(min_length=1, max_length=500)
    queue_after_create: bool = False

    @model_validator(mode="after")
    def validate_despatch(self):
        if self.planned_delivery_at < self.planned_despatch_at:
            raise ValueError("Planirani prijem ne može biti pre planirane otpreme")
        if self.planned_delivery_at < self.actual_despatch_at:
            raise ValueError("Planirani prijem ne može biti pre stvarne otpreme")
        carrier_fields = (
            self.carrier_name,
            self.carrier_tax_id,
            self.carrier_registration_number,
        )
        if any(carrier_fields) and not all(carrier_fields):
            raise ValueError("Naziv, PIB i matični broj prevoznika unose se zajedno")
        if self.driver_name and not self.driver_email:
            raise ValueError("Email vozača je obavezan kada je uneto ime vozača")
        return self


DocumentFormCreate = InvoiceFormCreate | DespatchFormCreate


class DocumentOut(DocumentCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: DocumentStatus
    remote_status: str | None
    remote_status_at: datetime | None
    external_id: str | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class ArtifactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    document_id: UUID
    kind: str
    content_type: str
    size_bytes: int
    sha256: str
    created_at: datetime


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    document_id: UUID
    kind: str
    status: JobStatus
    attempts: int
    max_attempts: int
    available_at: datetime
    finished_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class ExternalEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    provider: Provider
    stream: str
    external_event_id: str
    event_type: str
    occurred_at: datetime | None
    request_id: str | None
    data: dict
    created_at: datetime


class SyncCursorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    provider: Provider
    stream: str
    watermark: datetime | None
    page: int
    cursor_data: dict
    updated_at: datetime
