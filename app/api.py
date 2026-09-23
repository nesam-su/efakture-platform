from datetime import UTC, datetime, timedelta
from uuid import UUID

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
from sqlalchemy import func, select, text, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_invitation_secret,
    encrypt_secret,
    hash_invitation_secret,
    hash_password,
    verify_password,
)
from app.db import get_db
from app.dependencies import TenantContext, current_user, require_roles, tenant_context
from app.models import (
    AuditEvent,
    BackgroundJob,
    BusinessDocument,
    Direction,
    DocumentArtifact,
    DocumentStatus,
    IntegrationCredential,
    JobStatus,
    Membership,
    MembershipInvitation,
    Organization,
    Role,
    User,
)
from app.schemas import (
    ArtifactOut,
    BootstrapRequest,
    CredentialOut,
    CredentialUpsert,
    DocumentCreate,
    DocumentOut,
    InvitationAccept,
    InvitationCreate,
    InvitationIssued,
    InvitationOut,
    JobOut,
    LoginRequest,
    MembershipOut,
    OrganizationCreate,
    OrganizationOut,
    TokenResponse,
)
from app.storage import ArtifactTooLarge, LocalArtifactStore

router = APIRouter(prefix="/api/v1")
settings = get_settings()
artifact_store = LocalArtifactStore(settings.artifact_storage_path, settings.max_artifact_bytes)


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
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/auth/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.email == data.email.lower()))
    if (
        user is None
        or not user.is_active
        or not verify_password(data.password.get_secret_value(), user.password_hash)
    ):
        raise HTTPException(status_code=401, detail="Pogrešan email ili lozinka")
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/auth/invitations/accept", response_model=TokenResponse)
async def accept_invitation(data: InvitationAccept, db: AsyncSession = Depends(get_db)):
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
    await db.commit()
    return TokenResponse(access_token=create_access_token(user.id))


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
        role=Role.owner,
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
            base_url=data.base_url,
            encrypted_api_key=encrypt_secret(data.api_key.get_secret_value()),
            settings=data.settings,
        )
        db.add(credential)
    else:
        credential.base_url = data.base_url
        credential.encrypted_api_key = encrypt_secret(data.api_key.get_secret_value())
        credential.settings = data.settings
    await db.flush()
    db.add(
        AuditEvent(
            organization_id=context.organization_id,
            actor_user_id=context.user.id,
            action="integration.upsert",
            entity_type="integration_credential",
            entity_id=str(credential.id),
            details={"provider": data.provider.value},
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
