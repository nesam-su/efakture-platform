from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db import get_db
from app.models import AuthSession, Membership, Role, User

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class TenantContext:
    organization_id: UUID
    user: User
    role: Role


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: AuthSession


async def current_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Prijava je obavezna")
    try:
        claims = decode_access_token(credentials.credentials)
    except jwt.InvalidTokenError, ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token nije važeći"
        ) from None
    row = (
        await db.execute(
            select(User, AuthSession)
            .join(AuthSession, AuthSession.user_id == User.id)
            .where(
                User.id == claims.user_id,
                User.is_active.is_(True),
                AuthSession.id == claims.session_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > datetime.now(UTC),
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesija nije aktivna")
    user, session = row
    return AuthContext(user=user, session=session)


async def current_user(auth: AuthContext = Depends(current_auth)) -> User:
    return auth.user


async def tenant_context(
    x_organization_id: UUID = Header(alias="X-Organization-Id"),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> TenantContext:
    membership = await db.scalar(
        select(Membership).where(
            Membership.organization_id == x_organization_id,
            Membership.user_id == user.id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Nemate pristup firmi")
    return TenantContext(x_organization_id, user, membership.role)


def require_roles(*allowed: Role):
    async def check(context: TenantContext = Depends(tenant_context)) -> TenantContext:
        if context.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Nedovoljna ovlašćenja"
            )
        return context

    return check
