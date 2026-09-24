"""Add password reset, TOTP MFA and transactional email outbox."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_password_reset_mfa_email"
down_revision = "0006_auth_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    email_status = postgresql.ENUM(
        "queued", "sending", "retrying", "sent", "failed", name="email_status", create_type=False
    )
    email_status.create(op.get_bind(), checkfirst=True)
    op.add_column("users", sa.Column("encrypted_totp_secret", sa.Text()))
    op.add_column("users", sa.Column("totp_enabled_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("totp_last_counter", sa.BigInteger()))
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("requested_ip", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])
    op.create_index("ix_password_reset_tokens_expires_at", "password_reset_tokens", ["expires_at"])
    op.create_index(
        "ix_password_reset_user_active",
        "password_reset_tokens",
        ["user_id", "used_at", "expires_at"],
    )
    op.create_table(
        "mfa_recovery_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "code_hash"),
    )
    op.create_index("ix_mfa_recovery_codes_user_id", "mfa_recovery_codes", ["user_id"])
    op.create_table(
        "email_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("recipient_email", sa.String(320), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("subject", sa.String(300), nullable=False),
        sa.Column("text_body", sa.Text(), nullable=False),
        sa.Column("status", email_status, nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("locked_by", sa.String(200)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_email_outbox_claim", "email_outbox", ["status", "available_at", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("email_outbox")
    op.drop_table("mfa_recovery_codes")
    op.drop_table("password_reset_tokens")
    op.drop_column("users", "totp_last_counter")
    op.drop_column("users", "totp_enabled_at")
    op.drop_column("users", "encrypted_totp_secret")
    postgresql.ENUM(name="email_status").drop(op.get_bind(), checkfirst=True)
