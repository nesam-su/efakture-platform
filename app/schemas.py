from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr

from app.integrations.environments import IntegrationEnvironment
from app.models import Direction, DocumentStatus, JobStatus, Provider, Role


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
