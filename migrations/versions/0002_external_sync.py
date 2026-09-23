"""Add documented remote status, request tracking, and synchronization cursors."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_external_sync"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def timestamps():
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def upgrade() -> None:
    request_provider = postgresql.ENUM(
        "sef", "eotpremnice", name="external_request_provider", create_type=False
    )
    cursor_provider = postgresql.ENUM(
        "sef", "eotpremnice", name="sync_cursor_provider", create_type=False
    )
    request_provider.create(op.get_bind(), checkfirst=True)
    cursor_provider.create(op.get_bind(), checkfirst=True)

    op.add_column("business_documents", sa.Column("remote_status", sa.String(80)))
    op.add_column("business_documents", sa.Column("remote_status_at", sa.DateTime(timezone=True)))
    op.create_index("ix_business_documents_remote_status", "business_documents", ["remote_status"])

    op.create_table(
        "external_requests",
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
            sa.ForeignKey("business_documents.id", ondelete="SET NULL"),
        ),
        sa.Column("provider", request_provider, nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(80), nullable=False, server_default="Pending"),
        sa.Column("response_payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("business_messages", postgresql.JSONB(), nullable=False, server_default="[]"),
        *timestamps(),
        sa.UniqueConstraint("organization_id", "provider", "request_id"),
    )
    op.create_index(
        "ix_external_requests_organization_id", "external_requests", ["organization_id"]
    )
    op.create_index("ix_external_requests_document_id", "external_requests", ["document_id"])
    op.create_index(
        "ix_external_request_poll", "external_requests", ["provider", "status", "updated_at"]
    )

    op.create_table(
        "sync_cursors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", cursor_provider, nullable=False),
        sa.Column("stream", sa.String(120), nullable=False),
        sa.Column("watermark", sa.DateTime(timezone=True)),
        sa.Column("page", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cursor_data", postgresql.JSONB(), nullable=False, server_default="{}"),
        *timestamps(),
        sa.UniqueConstraint("organization_id", "provider", "stream"),
    )
    op.create_index("ix_sync_cursors_organization_id", "sync_cursors", ["organization_id"])


def downgrade() -> None:
    op.drop_table("sync_cursors")
    op.drop_table("external_requests")
    op.drop_index("ix_business_documents_remote_status", table_name="business_documents")
    op.drop_column("business_documents", "remote_status_at")
    op.drop_column("business_documents", "remote_status")
    postgresql.ENUM(name="sync_cursor_provider").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="external_request_provider").drop(op.get_bind(), checkfirst=True)
