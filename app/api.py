from datetime import UTC, datetime, time, timedelta
from urllib.parse import quote, urlencode
from uuid import UUID, uuid4

import httpx
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select, text, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_invitation_secret,
    create_one_time_secret,
    decrypt_secret,
    encrypt_secret,
    generate_recovery_codes,
    generate_totp_secret,
    hash_invitation_secret,
    hash_one_time_secret,
    hash_password,
    login_throttle_key,
    verify_password,
    verify_password_safe,
    verify_totp,
)
from app.db import get_db
from app.dependencies import (
    AuthContext,
    TenantContext,
    current_auth,
    current_user,
    require_roles,
    tenant_context,
)
from app.integrations.environments import integration_base_url
from app.integrations.eotpremnice import EotpremniceClient
from app.integrations.http import GovernmentApiError
from app.integrations.sef import SefClient
from app.mail import enqueue_email
from app.models import (
    AuditEvent,
    AuthSession,
    BackgroundJob,
    BusinessDocument,
    Direction,
    DocumentArtifact,
    DocumentStatus,
    ExternalEvent,
    IntegrationCredential,
    JobStatus,
    LoginThrottle,
    Membership,
    MembershipInvitation,
    MfaRecoveryCode,
    Organization,
    PasswordResetToken,
    Provider,
    Role,
    SyncCursor,
    User,
)
from app.schemas import (
    ArtifactOut,
    AuthSessionOut,
    BootstrapRequest,
    CredentialOut,
    CredentialUpsert,
    DespatchFormCreate,
    DocumentCreate,
    DocumentFormCreate,
    DocumentOut,
    ExternalEventOut,
    InvitationAccept,
    InvitationCreate,
    InvitationIssued,
    InvitationOut,
    JobOut,
    LoginRequest,
    MembershipOut,
    MessageResponse,
    MfaConfirmRequest,
    MfaRecoveryCodesResponse,
    MfaSetupRequest,
    MfaSetupResponse,
    OrganizationCreate,
    OrganizationOut,
    OrganizationProfileUpdate,
    PasswordResetConfirm,
    PasswordResetRequest,
    SyncCursorOut,
    TokenResponse,
)
from app.storage import ArtifactTooLarge, LocalArtifactStore
from app.ubl import generate_despatch_xml, generate_invoice_xml, invoice_totals

router = APIRouter(prefix="/api/v1")
settings = get_settings()
artifact_store = LocalArtifactStore(settings.artifact_storage_path, settings.max_artifact_bytes)


def _request_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def _create_session(db: AsyncSession, user: User, request: Request) -> AuthSession:
    session = AuthSession(
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(minutes=settings.access_token_minutes),
        ip_address=_request_ip(request),
        user_agent=request.headers.get("user-agent", "")[:500] or None,
    )
    db.add(session)
    await db.flush()
    return session


async def _tenant_document(
    db: AsyncSession, *, document_id: UUID, organization_id: UUID
) -> BusinessDocument:
    document = await db.scalar(
        select(BusinessDocument).where(
            BusinessDocument.id == document_id,
            BusinessDocument.organization_id == organization_id,
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Dokument nije pronađen")
    return document


@router.post("/auth/bootstrap", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def bootstrap(data: BootstrapRequest, request: Request, db: AsyncSession = Depends(get_db)):
    # Sprečava dva paralelna bootstrap zahteva sa različitim email adresama.
    await db.execute(text("SELECT pg_advisory_xact_lock(821734091)"))
    if await db.scalar(select(func.count(User.id))):
        raise HTTPException(status_code=409, detail="Početni administrator već postoji")
    user = User(
        email=data.admin_email.lower(),
        full_name=data.admin_name,
        password_hash=hash_password(data.password.get_secret_value()),
    )
    organization = Organization(
        name=data.organization_name,
        tax_id=data.tax_id,
        registration_number=data.registration_number,
    )
    db.add_all([user, organization])
    await db.flush()
    db.add(Membership(organization_id=organization.id, user_id=user.id, role=Role.owner))
    session = await _create_session(db, user, request)
    db.add(
        AuditEvent(
            organization_id=organization.id,
            actor_user_id=user.id,
            action="system.bootstrap",
            entity_type="organization",
            entity_id=str(organization.id),
            ip_address=request.client.host if request.client else None,
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Sistem je već inicijalizovan") from None
    return TokenResponse(access_token=create_access_token(user.id, session.id))


@router.post("/auth/login", response_model=TokenResponse)
async def login(data: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    now = datetime.now(UTC)
    email = data.email.lower()
    throttle_key = login_throttle_key(email, _request_ip(request))
    throttle = await db.scalar(
        select(LoginThrottle).where(LoginThrottle.key_hash == throttle_key).with_for_update()
    )
    if throttle and throttle.blocked_until and throttle.blocked_until > now:
        retry_after = max(1, int((throttle.blocked_until - now).total_seconds()))
        raise HTTPException(
            status_code=429,
            detail="Previše neuspešnih pokušaja. Pokušajte kasnije.",
            headers={"Retry-After": str(retry_after)},
        )
    # Zaključavanje korisničkog reda sprečava paralelnu upotrebu istog TOTP intervala.
    user = await db.scalar(select(User).where(User.email == email).with_for_update())
    password_valid = verify_password_safe(
        data.password.get_secret_value(), user.password_hash if user else None
    )
    mfa_valid = True
    accepted_counter: int | None = None
    recovery_code: MfaRecoveryCode | None = None
    if user is not None and password_valid and user.totp_enabled_at is not None:
        mfa_valid = False
        supplied_code = (data.mfa_code or "").strip().upper()
        if supplied_code.isdigit():
            accepted_counter = verify_totp(
                decrypt_secret(user.encrypted_totp_secret or ""),
                supplied_code,
                timestamp=int(now.timestamp()),
                last_counter=user.totp_last_counter,
            )
            mfa_valid = accepted_counter is not None
        elif supplied_code:
            recovery_code = await db.scalar(
                select(MfaRecoveryCode)
                .where(
                    MfaRecoveryCode.user_id == user.id,
                    MfaRecoveryCode.code_hash == hash_one_time_secret(supplied_code),
                    MfaRecoveryCode.used_at.is_(None),
                )
                .with_for_update()
            )
            mfa_valid = recovery_code is not None
    if user is None or not user.is_active or not password_valid or not mfa_valid:
        if throttle is None:
            throttle = LoginThrottle(
                key_hash=throttle_key,
                failed_attempts=0,
                window_started_at=now,
            )
            db.add(throttle)
        elif (now - throttle.window_started_at).total_seconds() > settings.login_window_seconds:
            throttle.failed_attempts = 0
            throttle.window_started_at = now
            throttle.blocked_until = None
        throttle.failed_attempts += 1
        if throttle.failed_attempts >= settings.login_max_attempts:
            throttle.blocked_until = now + timedelta(seconds=settings.login_block_seconds)
        await db.commit()
        raise HTTPException(status_code=401, detail="Pogrešan email, lozinka ili MFA kod")
    if throttle is not None:
        await db.delete(throttle)
    if accepted_counter is not None:
        user.totp_last_counter = accepted_counter
    if recovery_code is not None:
        recovery_code.used_at = now
    session = await _create_session(db, user, request)
    db.add(
        AuditEvent(
            actor_user_id=user.id,
            action="auth.login",
            entity_type="auth_session",
            entity_id=str(session.id),
            ip_address=_request_ip(request),
        )
    )
    await db.commit()
    return TokenResponse(access_token=create_access_token(user.id, session.id))


@router.post(
    "/auth/password-reset/request",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_password_reset(
    data: PasswordResetRequest, request: Request, db: AsyncSession = Depends(get_db)
):
    generic = "Ako nalog postoji, poslali smo uputstvo za promenu lozinke."
    now = datetime.now(UTC)
    request_key = login_throttle_key(f"password-reset:{data.email.lower()}", _request_ip(request))
    throttle = await db.scalar(
        select(LoginThrottle).where(LoginThrottle.key_hash == request_key).with_for_update()
    )
    if throttle is not None and throttle.blocked_until and throttle.blocked_until > now:
        return MessageResponse(message=generic)
    if throttle is None:
        throttle = LoginThrottle(
            key_hash=request_key,
            failed_attempts=1,
            window_started_at=now,
        )
        db.add(throttle)
    else:
        throttle.failed_attempts += 1
        throttle.window_started_at = now
    throttle.blocked_until = now + timedelta(seconds=60)
    user = await db.scalar(select(User).where(User.email == data.email.lower(), User.is_active))
    verify_password_safe("password-reset-timing", None)
    if user is None:
        await db.commit()
        return MessageResponse(message=generic)

    previous = (
        await db.scalars(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
        )
    ).all()
    for item in previous:
        item.used_at = now
    token, token_hash = create_one_time_secret()
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=now + timedelta(minutes=settings.password_reset_minutes),
            requested_ip=_request_ip(request),
        )
    )
    reset_url = f"{settings.public_base_url}/?reset_token={quote(token)}"
    db.add(
        enqueue_email(
            recipient=user.email,
            event_type="password_reset",
            subject="Promena lozinke za eDokumenti",
            text_body=(
                f"Zdravo {user.full_name},\n\n"
                f"Za promenu lozinke otvorite ovaj jednokratni link:\n{reset_url}\n\n"
                f"Link važi {settings.password_reset_minutes} minuta. "
                "Ako niste poslali zahtev, zanemarite ovu poruku."
            ),
        )
    )
    await db.commit()
    return MessageResponse(message=generic)


@router.post("/auth/password-reset/confirm", response_model=MessageResponse)
async def confirm_password_reset(
    data: PasswordResetConfirm, request: Request, db: AsyncSession = Depends(get_db)
):
    password = data.password.get_secret_value()
    if password != data.confirm_password.get_secret_value():
        raise HTTPException(status_code=422, detail="Lozinke se ne podudaraju")
    now = datetime.now(UTC)
    reset = await db.scalar(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == hash_one_time_secret(data.token))
        .with_for_update()
    )
    if reset is None or reset.used_at is not None or reset.expires_at <= now:
        raise HTTPException(status_code=400, detail="Link nije važeći ili je istekao")
    user = await db.get(User, reset.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=400, detail="Link nije važeći ili je istekao")
    user.password_hash = hash_password(password)
    reset.used_at = now
    sessions = (
        await db.scalars(
            select(AuthSession).where(
                AuthSession.user_id == user.id,
                AuthSession.revoked_at.is_(None),
            )
        )
    ).all()
    for session in sessions:
        session.revoked_at = now
    db.add(
        AuditEvent(
            actor_user_id=user.id,
            action="auth.password_reset",
            entity_type="user",
            entity_id=str(user.id),
            ip_address=_request_ip(request),
        )
    )
    db.add(
        enqueue_email(
            recipient=user.email,
            event_type="password_changed",
            subject="Lozinka za eDokumenti je promenjena",
            text_body=(
                f"Zdravo {user.full_name},\n\nLozinka je uspešno promenjena. "
                "Sve prethodne sesije su opozvane. Ako ovo niste bili vi, "
                "odmah kontaktirajte administratora."
            ),
        )
    )
    await db.commit()
    return MessageResponse(message="Lozinka je promenjena. Prijavite se ponovo.")


@router.post("/auth/mfa/setup", response_model=MfaSetupResponse)
async def setup_mfa(
    data: MfaSetupRequest,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(data.password.get_secret_value(), auth.user.password_hash):
        raise HTTPException(status_code=400, detail="Pogrešna lozinka")
    if auth.user.totp_enabled_at is not None:
        raise HTTPException(
            status_code=409,
            detail="MFA je već uključen; zamena zahteva poseban bezbednosni postupak",
        )
    secret = generate_totp_secret()
    auth.user.encrypted_totp_secret = encrypt_secret(secret)
    auth.user.totp_enabled_at = None
    auth.user.totp_last_counter = None
    await db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == auth.user.id))
    await db.commit()
    label = quote(f"eDokumenti:{auth.user.email}")
    query = urlencode(
        {"secret": secret, "issuer": "eDokumenti", "algorithm": "SHA1", "digits": 6, "period": 30}
    )
    return MfaSetupResponse(secret=secret, provisioning_uri=f"otpauth://totp/{label}?{query}")


@router.post("/auth/mfa/confirm", response_model=MfaRecoveryCodesResponse)
async def confirm_mfa(
    data: MfaConfirmRequest,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    if not auth.user.encrypted_totp_secret or auth.user.totp_enabled_at is not None:
        raise HTTPException(status_code=409, detail="MFA podešavanje nije započeto")
    now = datetime.now(UTC)
    counter = verify_totp(
        decrypt_secret(auth.user.encrypted_totp_secret),
        data.code,
        timestamp=int(now.timestamp()),
    )
    if counter is None:
        raise HTTPException(status_code=400, detail="Kod nije važeći")
    recovery_codes = generate_recovery_codes()
    auth.user.totp_enabled_at = now
    auth.user.totp_last_counter = counter
    db.add_all(
        [
            MfaRecoveryCode(user_id=auth.user.id, code_hash=hash_one_time_secret(code))
            for code in recovery_codes
        ]
    )
    db.add(
        AuditEvent(
            actor_user_id=auth.user.id,
            action="auth.mfa.enabled",
            entity_type="user",
            entity_id=str(auth.user.id),
        )
    )
    await db.commit()
    return MfaRecoveryCodesResponse(recovery_codes=recovery_codes)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    auth.session.revoked_at = datetime.now(UTC)
    db.add(
        AuditEvent(
            actor_user_id=auth.user.id,
            action="auth.logout",
            entity_type="auth_session",
            entity_id=str(auth.session.id),
            ip_address=_request_ip(request),
        )
    )
    await db.commit()


@router.get("/auth/sessions", response_model=list[AuthSessionOut])
async def list_auth_sessions(
    auth: AuthContext = Depends(current_auth), db: AsyncSession = Depends(get_db)
):
    sessions = list(
        (
            await db.scalars(
                select(AuthSession)
                .where(AuthSession.user_id == auth.user.id)
                .order_by(AuthSession.created_at.desc())
                .limit(50)
            )
        ).all()
    )
    return [
        AuthSessionOut(
            id=session.id,
            current=session.id == auth.session.id,
            ip_address=session.ip_address,
            user_agent=session.user_agent,
            expires_at=session.expires_at,
            revoked_at=session.revoked_at,
            created_at=session.created_at,
        )
        for session in sessions
    ]


@router.delete("/auth/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_auth_session(
    session_id: UUID,
    auth: AuthContext = Depends(current_auth),
    db: AsyncSession = Depends(get_db),
):
    session = await db.scalar(
        select(AuthSession).where(
            AuthSession.id == session_id,
            AuthSession.user_id == auth.user.id,
        )
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Sesija nije pronađena")
    session.revoked_at = datetime.now(UTC)
    await db.commit()


@router.post("/auth/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all_sessions(
    auth: AuthContext = Depends(current_auth), db: AsyncSession = Depends(get_db)
):
    sessions = (
        await db.scalars(
            select(AuthSession).where(
                AuthSession.user_id == auth.user.id,
                AuthSession.revoked_at.is_(None),
            )
        )
    ).all()
    now = datetime.now(UTC)
    for session in sessions:
        session.revoked_at = now
    await db.commit()


@router.post("/auth/invitations/accept", response_model=TokenResponse)
async def accept_invitation(
    data: InvitationAccept, request: Request, db: AsyncSession = Depends(get_db)
):
    now = datetime.now(UTC)
    invitation = await db.scalar(
        select(MembershipInvitation)
        .where(MembershipInvitation.token_hash == hash_invitation_secret(data.invitation_token))
        .with_for_update()
    )
    if (
        invitation is None
        or invitation.accepted_at is not None
        or invitation.revoked_at is not None
        or invitation.expires_at <= now
    ):
        raise HTTPException(status_code=400, detail="Poziv nije važeći ili je istekao")

    user = await db.scalar(select(User).where(User.email == invitation.email))
    if user is None:
        if not data.full_name:
            raise HTTPException(status_code=422, detail="Ime je obavezno za novog korisnika")
        user = User(
            email=invitation.email,
            full_name=data.full_name,
            password_hash=hash_password(data.password.get_secret_value()),
        )
        db.add(user)
        await db.flush()
    elif not user.is_active or not verify_password(
        data.password.get_secret_value(), user.password_hash
    ):
        raise HTTPException(status_code=401, detail="Pogrešna lozinka postojećeg korisnika")

    existing = await db.scalar(
        select(Membership).where(
            Membership.organization_id == invitation.organization_id,
            Membership.user_id == user.id,
        )
    )
    if existing is None:
        db.add(
            Membership(
                organization_id=invitation.organization_id,
                user_id=user.id,
                role=invitation.role,
            )
        )
    invitation.accepted_at = now
    db.add(
        AuditEvent(
            organization_id=invitation.organization_id,
            actor_user_id=user.id,
            action="membership.invitation.accept",
            entity_type="membership_invitation",
            entity_id=str(invitation.id),
            details={"role": invitation.role.value},
        )
    )
    session = await _create_session(db, user, request)
    await db.commit()
    return TokenResponse(access_token=create_access_token(user.id, session.id))


@router.get("/organizations", response_model=list[OrganizationOut])
async def organizations(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(Organization, Membership.role)
            .join(Membership, Membership.organization_id == Organization.id)
            .where(Membership.user_id == user.id, Organization.is_active.is_(True))
            .order_by(Organization.name)
        )
    ).all()
    return [
        OrganizationOut(
            id=organization.id,
            name=organization.name,
            tax_id=organization.tax_id,
            registration_number=organization.registration_number,
            profile=organization.profile,
            role=role,
        )
        for organization, role in rows
    ]


@router.post("/organizations", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
async def create_organization(
    data: OrganizationCreate,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    organization = Organization(**data.model_dump())
    db.add(organization)
    await db.flush()
    db.add(Membership(organization_id=organization.id, user_id=user.id, role=Role.owner))
    db.add(
        AuditEvent(
            organization_id=organization.id,
            actor_user_id=user.id,
            action="organization.create",
            entity_type="organization",
            entity_id=str(organization.id),
        )
    )
    await db.commit()
    await db.refresh(organization)
    return OrganizationOut(
        id=organization.id,
        name=organization.name,
        tax_id=organization.tax_id,
        registration_number=organization.registration_number,
        profile=organization.profile,
        role=Role.owner,
    )


@router.patch("/organizations/current", response_model=OrganizationOut)
async def update_organization_profile(
    data: OrganizationProfileUpdate,
    context: TenantContext = Depends(require_roles(Role.owner, Role.admin)),
    db: AsyncSession = Depends(get_db),
):
    organization = await db.get(Organization, context.organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Firma nije pronađena")
    organization.name = data.name
    organization.tax_id = data.tax_id
    organization.registration_number = data.registration_number
    organization.profile = data.model_dump(
        mode="json", exclude={"name", "tax_id", "registration_number"}
    )
    db.add(
        AuditEvent(
            organization_id=organization.id,
            actor_user_id=context.user.id,
            action="organization.profile.update",
            entity_type="organization",
            entity_id=str(organization.id),
        )
    )
    await db.commit()
    await db.refresh(organization)
    return OrganizationOut(
        id=organization.id,
        name=organization.name,
        tax_id=organization.tax_id,
        registration_number=organization.registration_number,
        profile=organization.profile,
        role=context.role,
    )


@router.get("/members", response_model=list[MembershipOut])
async def list_members(
    context: TenantContext = Depends(tenant_context), db: AsyncSession = Depends(get_db)
):
    rows = (
        await db.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.organization_id == context.organization_id)
            .order_by(User.full_name, User.email)
        )
    ).all()
    return [
        MembershipOut(
            id=membership.id,
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=membership.role,
            is_active=user.is_active,
        )
        for membership, user in rows
    ]


@router.post("/invitations", response_model=InvitationIssued, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    data: InvitationCreate,
    context: TenantContext = Depends(require_roles(Role.owner, Role.admin)),
    db: AsyncSession = Depends(get_db),
):
    if data.role == Role.owner and context.role != Role.owner:
        raise HTTPException(status_code=403, detail="Samo vlasnik može pozvati drugog vlasnika")
    email = str(data.email).lower()
    existing_user = await db.scalar(select(User).where(User.email == email))
    if existing_user is not None:
        existing_membership = await db.scalar(
            select(Membership).where(
                Membership.organization_id == context.organization_id,
                Membership.user_id == existing_user.id,
            )
        )
        if existing_membership is not None:
            raise HTTPException(status_code=409, detail="Korisnik je već član firme")

    now = datetime.now(UTC)
    active_invitations = (
        await db.scalars(
            select(MembershipInvitation).where(
                MembershipInvitation.organization_id == context.organization_id,
                MembershipInvitation.email == email,
                MembershipInvitation.accepted_at.is_(None),
                MembershipInvitation.revoked_at.is_(None),
            )
        )
    ).all()
    for previous in active_invitations:
        previous.revoked_at = now

    secret, token_hash = create_invitation_secret()
    invitation = MembershipInvitation(
        organization_id=context.organization_id,
        invited_by_user_id=context.user.id,
        email=email,
        role=data.role,
        token_hash=token_hash,
        expires_at=now + timedelta(hours=data.expires_in_hours),
    )
    db.add(invitation)
    await db.flush()
    invitation_url = f"{settings.public_base_url}/?invitation_token={quote(secret)}"
    db.add(
        enqueue_email(
            recipient=invitation.email,
            event_type="membership_invitation",
            subject="Poziv za pristup aplikaciji eDokumenti",
            text_body=(
                "Pozvani ste da pristupite firmi u aplikaciji eDokumenti.\n\n"
                f"Otvorite jednokratni link:\n{invitation_url}\n\n"
                f"Poziv važi {data.expires_in_hours} sati. Ako poziv niste očekivali, "
                "zanemarite ovu poruku."
            ),
        )
    )
    db.add(
        AuditEvent(
            organization_id=context.organization_id,
            actor_user_id=context.user.id,
            action="membership.invitation.create",
            entity_type="membership_invitation",
            entity_id=str(invitation.id),
            details={"email": email, "role": data.role.value},
        )
    )
    await db.commit()
    await db.refresh(invitation)
    return InvitationIssued(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        expires_at=invitation.expires_at,
        accepted_at=invitation.accepted_at,
        revoked_at=invitation.revoked_at,
        created_at=invitation.created_at,
        invitation_token=secret,
    )


@router.get("/invitations", response_model=list[InvitationOut])
async def list_invitations(
    context: TenantContext = Depends(require_roles(Role.owner, Role.admin)),
    db: AsyncSession = Depends(get_db),
):
    return list(
        (
            await db.scalars(
                select(MembershipInvitation)
                .where(MembershipInvitation.organization_id == context.organization_id)
                .order_by(MembershipInvitation.created_at.desc())
            )
        ).all()
    )


@router.put("/integrations", response_model=CredentialOut)
async def upsert_credential(
    data: CredentialUpsert,
    context: TenantContext = Depends(require_roles(Role.owner, Role.admin)),
    db: AsyncSession = Depends(get_db),
):
    base_url = integration_base_url(data.provider, data.environment)
    credential_settings = {**data.settings, "environment": data.environment}
    credential = await db.scalar(
        select(IntegrationCredential).where(
            IntegrationCredential.organization_id == context.organization_id,
            IntegrationCredential.provider == data.provider,
        )
    )
    if credential is None:
        credential = IntegrationCredential(
            organization_id=context.organization_id,
            provider=data.provider,
            base_url=base_url,
            encrypted_api_key=encrypt_secret(data.api_key.get_secret_value()),
            settings=credential_settings,
        )
        db.add(credential)
    else:
        credential.base_url = base_url
        credential.encrypted_api_key = encrypt_secret(data.api_key.get_secret_value())
        credential.settings = credential_settings
    await db.flush()
    db.add(
        AuditEvent(
            organization_id=context.organization_id,
            actor_user_id=context.user.id,
            action="integration.upsert",
            entity_type="integration_credential",
            entity_id=str(credential.id),
            details={"provider": data.provider.value, "environment": data.environment},
        )
    )
    await db.commit()
    await db.refresh(credential)
    return credential


@router.get("/integrations", response_model=list[CredentialOut])
async def list_credentials(
    context: TenantContext = Depends(tenant_context), db: AsyncSession = Depends(get_db)
):
    return list(
        (
            await db.scalars(
                select(IntegrationCredential)
                .where(IntegrationCredential.organization_id == context.organization_id)
                .order_by(IntegrationCredential.provider)
            )
        ).all()
    )


@router.post("/integrations/{provider}/test", response_model=MessageResponse)
async def test_credential(
    provider: Provider,
    context: TenantContext = Depends(require_roles(Role.owner, Role.admin)),
    db: AsyncSession = Depends(get_db),
):
    credential = await db.scalar(
        select(IntegrationCredential).where(
            IntegrationCredential.organization_id == context.organization_id,
            IntegrationCredential.provider == provider,
            IntegrationCredential.is_active.is_(True),
        )
    )
    if credential is None:
        raise HTTPException(status_code=404, detail="Integracija nije povezana")

    api_key = decrypt_secret(credential.encrypted_api_key)
    try:
        if provider == Provider.sef:
            async with SefClient(api_key=api_key, base_url=credential.base_url) as client:
                await client.version()
        else:
            async with EotpremniceClient(api_key=api_key, base_url=credential.base_url) as client:
                await client.request_changes(datetime.now(UTC).date(), page=0)
    except GovernmentApiError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Državni servis je odbio proveru (HTTP {exc.status_code})",
        ) from None
    except httpx.RequestError:
        raise HTTPException(
            status_code=502, detail="Državni servis trenutno nije dostupan"
        ) from None

    environment = credential.settings.get("environment", "demo")
    label = "Demo" if environment == "demo" else "Produkcijska"
    return MessageResponse(message=f"{label} veza je uspešno proverena.")


@router.post("/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def create_document(
    data: DocumentCreate,
    context: TenantContext = Depends(
        require_roles(Role.owner, Role.admin, Role.accountant, Role.operator)
    ),
    db: AsyncSession = Depends(get_db),
):
    document = BusinessDocument(organization_id=context.organization_id, **data.model_dump())
    db.add(document)
    try:
        await db.flush()
        db.add(
            AuditEvent(
                organization_id=context.organization_id,
                actor_user_id=context.user.id,
                action="document.create",
                entity_type="business_document",
                entity_id=str(document.id),
                details={
                    "provider": data.provider.value,
                    "direction": data.direction.value,
                    "document_type": data.document_type,
                },
            )
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Idempotency ključ već postoji") from None
    await db.refresh(document)
    return document


@router.post(
    "/documents/from-form", response_model=DocumentOut, status_code=status.HTTP_201_CREATED
)
async def create_document_from_form(
    data: DocumentFormCreate,
    context: TenantContext = Depends(
        require_roles(Role.owner, Role.admin, Role.accountant, Role.operator)
    ),
    db: AsyncSession = Depends(get_db),
):
    organization = await db.get(Organization, context.organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Firma nije pronađena")
    try:
        if isinstance(data, DespatchFormCreate):
            xml = generate_despatch_xml(organization, data)
            provider = Provider.eotpremnice
            document_type = "despatch_advice"
            currency = None
            total_amount = None
            filename = f"otpremnica-{data.document_number}.xml"
        else:
            xml = generate_invoice_xml(organization, data)
            provider = Provider.sef
            document_type = "sales_invoice"
            currency = data.currency.upper()
            total_amount = invoice_totals(data)[2]
            filename = f"faktura-{data.document_number}.xml"
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="Dopunite poslovni profil izabrane firme pre kreiranja dokumenta",
        ) from exc

    document = BusinessDocument(
        organization_id=organization.id,
        provider=provider,
        direction=Direction.outbound,
        document_type=document_type,
        document_number=data.document_number,
        idempotency_key=f"form-{uuid4()}",
        issue_date=datetime.combine(data.issue_date, time.min, tzinfo=UTC),
        counterparty_name=data.customer.name,
        counterparty_tax_id=data.customer.tax_id,
        currency=currency,
        total_amount=total_amount,
        payload={"source": "business_form", "form": data.model_dump(mode="json")},
    )
    db.add(document)
    stored = None
    try:
        await db.flush()
        stored = await artifact_store.put_bytes(
            organization_id=organization.id,
            document_id=document.id,
            filename=filename,
            content=xml,
        )
        artifact = DocumentArtifact(
            organization_id=organization.id,
            document_id=document.id,
            kind="generated_xml",
            object_key=stored.object_key,
            content_type="application/xml",
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
        )
        db.add(artifact)
        await db.flush()
        if data.queue_after_create:
            db.add(
                BackgroundJob(
                    organization_id=organization.id,
                    document_id=document.id,
                    kind="send_document",
                    payload={"artifact_id": str(artifact.id)},
                )
            )
            document.status = DocumentStatus.queued
        db.add(
            AuditEvent(
                organization_id=organization.id,
                actor_user_id=context.user.id,
                action="document.generate",
                entity_type="business_document",
                entity_id=str(document.id),
                details={
                    "provider": provider.value,
                    "document_type": document_type,
                    "queued": data.queue_after_create,
                },
            )
        )
        await db.commit()
    except Exception:
        await db.rollback()
        if stored is not None:
            artifact_store.delete(stored.object_key)
        raise
    await db.refresh(document)
    return document


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    limit: int = Query(default=50, ge=1, le=200),
    before_created_at: datetime | None = None,
    before_id: UUID | None = None,
    context: TenantContext = Depends(tenant_context),
    db: AsyncSession = Depends(get_db),
):
    query = select(BusinessDocument).where(
        BusinessDocument.organization_id == context.organization_id
    )
    if (before_created_at is None) != (before_id is None):
        raise HTTPException(status_code=422, detail="Oba cursor parametra su obavezna")
    if before_created_at is not None and before_id is not None:
        query = query.where(
            tuple_(BusinessDocument.created_at, BusinessDocument.id)
            < tuple_(before_created_at, before_id)
        )
    query = query.order_by(BusinessDocument.created_at.desc(), BusinessDocument.id.desc())
    return list((await db.scalars(query.limit(limit))).all())


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: UUID,
    context: TenantContext = Depends(tenant_context),
    db: AsyncSession = Depends(get_db),
):
    return await _tenant_document(
        db, document_id=document_id, organization_id=context.organization_id
    )


@router.post(
    "/documents/{document_id}/artifacts",
    response_model=ArtifactOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document_artifact(
    document_id: UUID,
    kind: str = Form(min_length=1, max_length=50),
    file: UploadFile = File(),
    context: TenantContext = Depends(
        require_roles(Role.owner, Role.admin, Role.accountant, Role.operator)
    ),
    db: AsyncSession = Depends(get_db),
):
    document = await _tenant_document(
        db, document_id=document_id, organization_id=context.organization_id
    )
    content_type = (file.content_type or "application/octet-stream").lower()
    if content_type not in {"application/xml", "text/xml", "application/pdf"}:
        await file.close()
        raise HTTPException(status_code=415, detail="Dozvoljeni su XML i PDF prilozi")
    try:
        stored = await artifact_store.put_upload(
            organization_id=context.organization_id,
            document_id=document.id,
            upload=file,
        )
    except ArtifactTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    existing = await db.scalar(
        select(DocumentArtifact).where(
            DocumentArtifact.document_id == document.id,
            DocumentArtifact.sha256 == stored.sha256,
        )
    )
    if existing is not None:
        artifact_store.delete(stored.object_key)
        return existing

    artifact = DocumentArtifact(
        organization_id=context.organization_id,
        document_id=document.id,
        kind=kind,
        object_key=stored.object_key,
        content_type=content_type,
        size_bytes=stored.size_bytes,
        sha256=stored.sha256,
    )
    db.add(artifact)
    await db.flush()
    db.add(
        AuditEvent(
            organization_id=context.organization_id,
            actor_user_id=context.user.id,
            action="document.artifact.upload",
            entity_type="document_artifact",
            entity_id=str(artifact.id),
            details={"document_id": str(document.id), "kind": kind, "sha256": stored.sha256},
        )
    )
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        artifact_store.delete(stored.object_key)
        raise
    await db.refresh(artifact)
    return artifact


@router.get("/documents/{document_id}/artifacts", response_model=list[ArtifactOut])
async def list_document_artifacts(
    document_id: UUID,
    context: TenantContext = Depends(tenant_context),
    db: AsyncSession = Depends(get_db),
):
    await _tenant_document(db, document_id=document_id, organization_id=context.organization_id)
    return list(
        (
            await db.scalars(
                select(DocumentArtifact)
                .where(
                    DocumentArtifact.document_id == document_id,
                    DocumentArtifact.organization_id == context.organization_id,
                )
                .order_by(DocumentArtifact.created_at)
            )
        ).all()
    )


@router.get("/documents/{document_id}/artifacts/{artifact_id}/download")
async def download_document_artifact(
    document_id: UUID,
    artifact_id: UUID,
    context: TenantContext = Depends(tenant_context),
    db: AsyncSession = Depends(get_db),
):
    artifact = await db.scalar(
        select(DocumentArtifact).where(
            DocumentArtifact.id == artifact_id,
            DocumentArtifact.document_id == document_id,
            DocumentArtifact.organization_id == context.organization_id,
        )
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="Prilog nije pronađen")
    path = artifact_store.resolve(artifact.object_key)
    if not path.is_file():
        raise HTTPException(status_code=410, detail="Sadržaj priloga nije dostupan")
    return FileResponse(
        path, media_type=artifact.content_type, filename=path.name.split("-", 1)[-1]
    )


@router.post("/documents/{document_id}/queue", response_model=JobOut)
async def queue_document(
    document_id: UUID,
    context: TenantContext = Depends(
        require_roles(Role.owner, Role.admin, Role.accountant, Role.operator)
    ),
    db: AsyncSession = Depends(get_db),
):
    document = await _tenant_document(
        db, document_id=document_id, organization_id=context.organization_id
    )
    if document.direction != Direction.outbound:
        raise HTTPException(status_code=409, detail="Samo izlazni dokument može biti poslat")
    artifact = await db.scalar(
        select(DocumentArtifact)
        .where(
            DocumentArtifact.document_id == document.id,
            DocumentArtifact.organization_id == context.organization_id,
            DocumentArtifact.content_type.in_(["application/xml", "text/xml"]),
        )
        .order_by(DocumentArtifact.created_at.desc())
    )
    if artifact is None:
        raise HTTPException(status_code=409, detail="Dokument nema XML prilog za slanje")

    job = await db.scalar(
        select(BackgroundJob).where(
            BackgroundJob.document_id == document.id,
            BackgroundJob.kind == "send_document",
        )
    )
    if job is None:
        job = BackgroundJob(
            organization_id=context.organization_id,
            document_id=document.id,
            kind="send_document",
            payload={"artifact_id": str(artifact.id)},
        )
        db.add(job)
    elif job.status in {JobStatus.queued, JobStatus.running, JobStatus.retrying}:
        return job
    elif job.status == JobStatus.succeeded:
        raise HTTPException(status_code=409, detail="Dokument je već uspešno poslat")
    else:
        job.status = JobStatus.queued
        job.payload = {"artifact_id": str(artifact.id)}
        job.attempts = 0
        job.available_at = datetime.now(UTC)
        job.finished_at = None
        job.last_error = None

    document.status = DocumentStatus.queued
    await db.flush()
    db.add(
        AuditEvent(
            organization_id=context.organization_id,
            actor_user_id=context.user.id,
            action="document.queue",
            entity_type="background_job",
            entity_id=str(job.id),
            details={"document_id": str(document.id), "provider": document.provider.value},
        )
    )
    await db.commit()
    await db.refresh(job)
    return job


@router.get("/jobs", response_model=list[JobOut])
async def list_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    context: TenantContext = Depends(tenant_context),
    db: AsyncSession = Depends(get_db),
):
    return list(
        (
            await db.scalars(
                select(BackgroundJob)
                .where(BackgroundJob.organization_id == context.organization_id)
                .order_by(BackgroundJob.created_at.desc())
                .limit(limit)
            )
        ).all()
    )


@router.get("/external-events", response_model=list[ExternalEventOut])
async def list_external_events(
    limit: int = Query(default=100, ge=1, le=500),
    provider: Provider | None = None,
    context: TenantContext = Depends(tenant_context),
    db: AsyncSession = Depends(get_db),
):
    query = select(ExternalEvent).where(ExternalEvent.organization_id == context.organization_id)
    if provider is not None:
        query = query.where(ExternalEvent.provider == provider)
    query = query.order_by(ExternalEvent.occurred_at.desc().nullslast(), ExternalEvent.id.desc())
    return list((await db.scalars(query.limit(limit))).all())


@router.get("/sync-cursors", response_model=list[SyncCursorOut])
async def list_sync_cursors(
    context: TenantContext = Depends(require_roles(Role.owner, Role.admin, Role.accountant)),
    db: AsyncSession = Depends(get_db),
):
    return list(
        (
            await db.scalars(
                select(SyncCursor)
                .where(SyncCursor.organization_id == context.organization_id)
                .order_by(SyncCursor.provider, SyncCursor.stream)
            )
        ).all()
    )
