"""Initial schema - DailyFeed Phase 1

Revision ID: 0001
Revises:
Create Date: 2026-06-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=128), nullable=False),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("settings", sa.JSON(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_is_active", "users", ["is_active"])

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_url", sa.String(length=1024), nullable=False),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("priority", sa.SmallInteger(), default=3),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("last_fetch_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])
    op.create_index("ix_subscriptions_source_type", "subscriptions", ["source_type"])
    op.create_index("ix_subscriptions_is_active", "subscriptions", ["is_active"])
    op.create_index("ix_subscriptions_priority", "subscriptions", ["priority"])

    op.create_table(
        "contents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("author", sa.String(length=128), nullable=True),
        sa.Column("raw_content", sa.Text(), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"]),
    )
    op.create_index("ix_contents_subscription_id", "contents", ["subscription_id"])
    op.create_index("ix_contents_content_hash", "contents", ["content_hash"])
    op.create_index("ix_contents_published_at", "contents", ["published_at"])

    op.create_table(
        "summaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("generated_by", sa.String(length=32), default="llm"),
        sa.Column("tokens_used", sa.Integer(), default=0),
        sa.Column("duration_ms", sa.Integer(), default=0),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["content_id"], ["contents.id"]),
    )
    op.create_index("ix_summaries_content_id", "summaries", ["content_id"])

    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=True),
        sa.Column("markdown_body", sa.Text(), nullable=True),
        sa.Column("html_body", sa.Text(), nullable=True),
        sa.Column("stats", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), default="draft"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_reports_user_id", "reports", ["user_id"])
    op.create_index("ix_reports_report_date", "reports", ["report_date"])
    op.create_index("ix_reports_status", "reports", ["status"])

    op.create_table(
        "push_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"]),
    )
    op.create_index("ix_push_logs_report_id", "push_logs", ["report_id"])
    op.create_index("ix_push_logs_channel", "push_logs", ["channel"])


def downgrade() -> None:
    op.drop_index("ix_push_logs_channel", table_name="push_logs")
    op.drop_index("ix_push_logs_report_id", table_name="push_logs")
    op.drop_table("push_logs")

    op.drop_index("ix_reports_status", table_name="reports")
    op.drop_index("ix_reports_report_date", table_name="reports")
    op.drop_index("ix_reports_user_id", table_name="reports")
    op.drop_table("reports")

    op.drop_index("ix_summaries_content_id", table_name="summaries")
    op.drop_table("summaries")

    op.drop_index("ix_contents_published_at", table_name="contents")
    op.drop_index("ix_contents_content_hash", table_name="contents")
    op.drop_index("ix_contents_subscription_id", table_name="contents")
    op.drop_table("contents")

    op.drop_index("ix_subscriptions_priority", table_name="subscriptions")
    op.drop_index("ix_subscriptions_is_active", table_name="subscriptions")
    op.drop_index("ix_subscriptions_source_type", table_name="subscriptions")
    op.drop_index("ix_subscriptions_user_id", table_name="subscriptions")
    op.drop_table("subscriptions")

    op.drop_index("ix_users_is_active", table_name="users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
