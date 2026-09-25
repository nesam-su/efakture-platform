"""Add reusable customers and catalog items."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_customers_catalog"
down_revision = "0008_organization_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("tax_id", sa.String(20), nullable=False),
        sa.Column("registration_number", sa.String(30)),
        sa.Column("street", sa.String(300), nullable=False),
        sa.Column("city", sa.String(120), nullable=False),
        sa.Column("postal_code", sa.String(20), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False, server_default="RS"),
        sa.Column("email", sa.String(320)),
        sa.Column("phone", sa.String(50)),
        sa.Column("jbkjs", sa.String(30)),
        sa.Column("notes", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "tax_id"),
    )
    op.create_index("ix_customers_organization_id", "customers", ["organization_id"])
    op.create_index("ix_customer_org_name", "customers", ["organization_id", "name"])

    op.create_table(
        "catalog_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("sku", sa.String(100), nullable=False),
        sa.Column("gtin", sa.String(30)),
        sa.Column("description", sa.Text()),
        sa.Column("unit_code", sa.String(3), nullable=False, server_default="H87"),
        sa.Column("unit_price", sa.Numeric(20, 6), nullable=False, server_default="0"),
        sa.Column("vat_rate", sa.Numeric(5, 2), nullable=False, server_default="20"),
        sa.Column("vat_category", sa.String(4), nullable=False, server_default="S"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "sku"),
    )
    op.create_index("ix_catalog_items_organization_id", "catalog_items", ["organization_id"])
    op.create_index("ix_catalog_item_org_name", "catalog_items", ["organization_id", "name"])


def downgrade() -> None:
    op.drop_table("catalog_items")
    op.drop_table("customers")
