"""Add idempotent external event journal and external document identity."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_external_events"
down_revision = "0004_artifact_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    event_provider = postgresql.ENUM(
        "sef", "eotpremnice", name="external_event_provider", create_type=False
    )
    event_provider.create(op.get_bind(), checkfirst=True)
    op.create_unique_constraint(
        "uq_document_org_provider_external",
        "business_documents",
        ["organization_id", "provider", "external_id"],
    )
    op.create_table(
        "external_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", event_provider, nullable=False),
        sa.Column("stream", sa.String(120), nullable=False),
        sa.Column("external_event_id", sa.String(200), nullable=False),
        sa.Column("event_type", sa.String(160), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True)),
        sa.Column("request_id", sa.String(128)),
        sa.Column("data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "organization_id",
            "provider",
            "stream",
            "external_event_id",
            name="uq_external_event_identity",
        ),
    )
    op.create_index("ix_external_events_organization_id", "external_events", ["organization_id"])
    op.create_index(
        "ix_external_event_org_time", "external_events", ["organization_id", "occurred_at"]
    )


def downgrade() -> None:
    op.drop_table("external_events")
    op.drop_constraint("uq_document_org_provider_external", "business_documents", type_="unique")
    postgresql.ENUM(name="external_event_provider").drop(op.get_bind(), checkfirst=True)
