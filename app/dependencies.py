from dataclasses import dataclass
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db import get_db
from app.models import Membership, Role, User

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class TenantContext:
    organization_id: UUID
    user: User
    role: Role


async def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Prijava je obavezna")
    try:
        user_id = decode_access_token(credentials.credentials)
    except jwt.InvalidTokenError, ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token nije važeći"
        ) from None
    user = await db.scalar(select(User).where(User.id == user_id, User.is_active.is_(True)))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Korisnik nije aktivan"
        )
    return user


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
