"""Add one-time membership invitations for multi-user organizations."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_membership_invitations"
down_revision = "0002_external_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    invitation_role = postgresql.ENUM(
        "owner",
        "admin",
        "accountant",
        "operator",
        "viewer",
        name="invitation_role",
        create_type=False,
    )
    invitation_role.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "membership_invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "invited_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("role", invitation_role, nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_membership_invitations_organization_id",
        "membership_invitations",
        ["organization_id"],
    )
    op.create_index(
        "ix_membership_invitations_invited_by_user_id",
        "membership_invitations",
        ["invited_by_user_id"],
    )
    op.create_index(
        "ix_invitation_org_email", "membership_invitations", ["organization_id", "email"]
    )
    op.create_index(
        "ix_invitation_expiry",
        "membership_invitations",
        ["expires_at", "accepted_at", "revoked_at"],
    )


def downgrade() -> None:
    op.drop_table("membership_invitations")
    postgresql.ENUM(name="invitation_role").drop(op.get_bind(), checkfirst=True)
