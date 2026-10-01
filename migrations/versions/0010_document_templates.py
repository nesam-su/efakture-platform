"""Add tenant-scoped reusable document templates."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_document_templates"
down_revision = "0009_customers_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    template_provider = postgresql.ENUM(
        "sef", "eotpremnice", name="document_template_provider", create_type=False
    )
    template_provider.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "document_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("provider", template_provider, nullable=False),
        sa.Column("document_type", sa.String(80), nullable=False),
        sa.Column("template_data", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "provider", "name"),
    )
    op.create_index(
        "ix_document_template_org_provider",
        "document_templates",
        ["organization_id", "provider"],
    )
    op.create_index(
        "ix_document_templates_organization_id", "document_templates", ["organization_id"]
    )
    op.create_index(
        "ix_document_templates_created_by_user_id", "document_templates", ["created_by_user_id"]
    )


def downgrade() -> None:
    op.drop_table("document_templates")
    postgresql.ENUM(name="document_template_provider").drop(op.get_bind(), checkfirst=True)
