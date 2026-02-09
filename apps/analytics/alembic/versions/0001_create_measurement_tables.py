"""create measurement tables

Revision ID: 0001
Revises:
Create Date: 2026-02-09
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("target_cac", sa.Numeric(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_table(
        "channel_snapshots",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("campaign_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=True),
        sa.Column("window_end", sa.Date(), nullable=True),
        sa.Column("spend", sa.Numeric(), nullable=False, server_default="0"),
        sa.Column("impressions", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("clicks", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("conversions", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("revenue", sa.Numeric(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"]),
    )

    op.create_table(
        "measurement_reports",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("campaign_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=True),
        sa.Column("window_end", sa.Date(), nullable=True),
        sa.Column("total_spend", sa.Numeric(), nullable=False, server_default="0"),
        sa.Column("total_impressions", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_clicks", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_conversions", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_revenue", sa.Numeric(), nullable=False, server_default="0"),
        sa.Column("metrics_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"]),
    )


def downgrade() -> None:
    op.drop_table("measurement_reports")
    op.drop_table("channel_snapshots")
    op.drop_table("campaigns")
