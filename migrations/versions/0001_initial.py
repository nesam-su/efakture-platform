"""Initial tenant-aware schema."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    role = postgresql.ENUM(
        "owner",
        "admin",
        "accountant",
        "operator",
        "viewer",
        name="membership_role",
        create_type=False,
    )
    provider_credential = postgresql.ENUM(
        "sef", "eotpremnice", name="integration_provider", create_type=False
    )
    provider_document = postgresql.ENUM(
        "sef", "eotpremnice", name="document_provider", create_type=False
    )
    direction = postgresql.ENUM("inbound", "outbound", name="document_direction", create_type=False)
    document_status = postgresql.ENUM(
        "draft",
        "queued",
        "sent",
        "delivered",
        "accepted",
        "rejected",
        "cancelled",
        "error",
        name="document_status",
        create_type=False,
    )
    for enum in (role, provider_credential, provider_document, direction, document_status):
        enum.create(op.get_bind(), checkfirst=True)

    def timestamps():
        return (
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("tax_id", sa.String(20), nullable=False),
        sa.Column("registration_number", sa.String(30)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
    )
    op.create_index("ix_organizations_tax_id", "organizations", ["tax_id"])
    op.create_table(
        "memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", role, nullable=False),
        *timestamps(),
        sa.UniqueConstraint("organization_id", "user_id"),
    )
    op.create_index("ix_memberships_organization_id", "memberships", ["organization_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    op.create_table(
        "integration_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", provider_credential, nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("settings", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
        sa.UniqueConstraint("organization_id", "provider"),
    )
    op.create_index(
        "ix_integration_credentials_organization_id", "integration_credentials", ["organization_id"]
    )
    op.create_table(
        "business_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", provider_document, nullable=False),
        sa.Column("direction", direction, nullable=False),
        sa.Column("document_type", sa.String(80), nullable=False),
        sa.Column("document_number", sa.String(100)),
        sa.Column("external_id", sa.String(200)),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("status", document_status, nullable=False, server_default="draft"),
        sa.Column("issue_date", sa.DateTime(timezone=True)),
        sa.Column("counterparty_name", sa.String(300)),
        sa.Column("counterparty_tax_id", sa.String(20)),
        sa.Column("currency", sa.String(3)),
        sa.Column("total_amount", sa.Numeric(20, 4)),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("last_error", sa.Text()),
        *timestamps(),
        sa.UniqueConstraint("organization_id", "provider", "idempotency_key"),
    )
    op.create_index(
        "ix_business_documents_organization_id", "business_documents", ["organization_id"]
    )
    op.create_index(
        "ix_document_org_created", "business_documents", ["organization_id", "created_at"]
    )
    op.create_index("ix_document_org_status", "business_documents", ["organization_id", "status"])
    op.create_index("ix_document_external", "business_documents", ["provider", "external_id"])
    op.create_table(
        "document_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("business_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("object_key", sa.String(1000), nullable=False),
        sa.Column("content_type", sa.String(150), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("document_id", "sha256"),
    )
    op.create_index(
        "ix_document_artifacts_organization_id", "document_artifacts", ["organization_id"]
    )
    op.create_index("ix_document_artifacts_document_id", "document_artifacts", ["document_id"])
    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("entity_type", sa.String(80)),
        sa.Column("entity_id", sa.String(100)),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_audit_events_organization_id", "audit_events", ["organization_id"])
    op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])
    op.create_index("ix_audit_org_time", "audit_events", ["organization_id", "created_at"])


def downgrade() -> None:
    for table in (
        "audit_events",
        "document_artifacts",
        "business_documents",
        "integration_credentials",
        "memberships",
        "organizations",
        "users",
    ):
        op.drop_table(table)
    for name in (
        "document_status",
        "document_direction",
        "document_provider",
        "integration_provider",
        "membership_role",
    ):
        postgresql.ENUM(name=name).drop(op.get_bind(), checkfirst=True)
