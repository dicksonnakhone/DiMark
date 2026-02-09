"""add strategist tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-02-09
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaign_briefs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("campaign_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("brief_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "budget_plans",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("campaign_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("total_budget", sa.Numeric(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False, server_default="USD"),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "channel_budgets",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("budget_plan_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("allocated_budget", sa.Numeric(), nullable=False),
        sa.ForeignKeyConstraint(["budget_plan_id"], ["budget_plans.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("budget_plan_id", "channel"),
    )

    op.create_table(
        "campaign_plans",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("campaign_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("budget_plan_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("plan_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["budget_plan_id"], ["budget_plans.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "allocation_decisions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("campaign_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("report_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("budget_plan_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("decision_type", sa.Text(), nullable=False),
        sa.Column("from_allocations_json", postgresql.JSONB(), nullable=False),
        sa.Column("to_allocations_json", postgresql.JSONB(), nullable=False),
        sa.Column("rationale_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["measurement_reports.id"]),
        sa.ForeignKeyConstraint(["budget_plan_id"], ["budget_plans.id"], ondelete="CASCADE"),
    )

    op.create_index(
        "ix_allocation_decisions_campaign_created",
        "allocation_decisions",
        ["campaign_id", "created_at"],
    )
    op.create_index(
        "ix_measurement_reports_campaign_created",
        "measurement_reports",
        ["campaign_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_measurement_reports_campaign_created", table_name="measurement_reports")
    op.drop_index("ix_allocation_decisions_campaign_created", table_name="allocation_decisions")
    op.drop_table("allocation_decisions")
    op.drop_table("campaign_plans")
    op.drop_table("channel_budgets")
    op.drop_table("budget_plans")
    op.drop_table("campaign_briefs")
