from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr

from app.models import Direction, DocumentStatus, Provider, Role


class BootstrapRequest(BaseModel):
    organization_name: str = Field(min_length=2, max_length=200)
    tax_id: str = Field(min_length=8, max_length=20)
    registration_number: str | None = Field(default=None, max_length=30)
    admin_name: str = Field(min_length=2, max_length=200)
    admin_email: EmailStr
    password: SecretStr = Field(min_length=12, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: SecretStr


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    tax_id: str
    registration_number: str | None
    role: Role | None = None


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    tax_id: str = Field(min_length=8, max_length=20)
    registration_number: str | None = Field(default=None, max_length=30)


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
    base_url: str = Field(pattern=r"^https://", max_length=500)
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
