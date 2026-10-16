"""Initial TradeVault schema; generated from the checked-in SQLAlchemy models."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("auth_version", sa.Integer(), nullable=False),
        sa.Column("onboarding_complete", sa.Boolean(), nullable=False),
        sa.Column("notify_journal", sa.Boolean(), nullable=False),
        sa.Column("notify_security", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"))
    op.create_index("ix_users_email", "users", ["email"])
    op.create_table("journal_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=80), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("image_hash", sa.String(length=16)),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("market", sa.String(length=80), nullable=False),
        sa.Column("reflection", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime()))
    for index, column in (("user_id", "user_id"), ("image_hash", "image_hash"), ("trade_date", "trade_date"), ("deleted_at", "deleted_at")):
        op.create_index(f"ix_journal_entries_{index}", "journal_entries", [column])
    op.create_table("password_resets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_password_resets_token_hash"))
    op.create_index("ix_password_resets_user_id", "password_resets", ["user_id"])
    op.create_index("ix_password_resets_token_hash", "password_resets", ["token_hash"])
    op.create_index("ix_password_resets_expires_at", "password_resets", ["expires_at"])
    op.create_table("notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("body", sa.String(length=240), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("read_at", sa.DateTime()))
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])


def downgrade():
    op.drop_table("notifications")
    op.drop_table("password_resets")
    op.drop_table("journal_entries")
    op.drop_table("users")
