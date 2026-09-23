"""Add durable PostgreSQL jobs for document processing."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_artifact_jobs"
down_revision = "0003_membership_invitations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    job_status = postgresql.ENUM(
        "queued",
        "running",
        "retrying",
        "succeeded",
        "failed",
        name="background_job_status",
        create_type=False,
    )
    job_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "background_jobs",
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
        sa.Column("kind", sa.String(80), nullable=False),
        sa.Column("status", job_status, nullable=False, server_default="queued"),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("locked_by", sa.String(200)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("document_id", "kind"),
    )
    op.create_index("ix_background_jobs_organization_id", "background_jobs", ["organization_id"])
    op.create_index("ix_background_jobs_document_id", "background_jobs", ["document_id"])
    op.create_index("ix_job_claim", "background_jobs", ["status", "available_at", "created_at"])
    op.create_index("ix_job_org_created", "background_jobs", ["organization_id", "created_at"])


def downgrade() -> None:
    op.drop_table("background_jobs")
    postgresql.ENUM(name="background_job_status").drop(op.get_bind(), checkfirst=True)
