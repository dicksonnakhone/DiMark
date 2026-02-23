"""add optimization learnings and monitor runs tables

Revision ID: 0007_action_learning_tables
Revises: 0006_optimization_tables
Create Date: 2026-02-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0007_action_learning_tables"
down_revision = "0006_optimization_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- optimization_learnings ----
    op.create_table(
        "optimization_learnings",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("campaign_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("proposal_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("method_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "predicted_impact",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "actual_impact",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("accuracy_score", sa.Numeric(), nullable=True),
        sa.Column(
            "verification_status",
            sa.Text(),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "details_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["campaigns.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"], ["optimization_proposals.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["method_id"], ["optimization_methods.id"]
        ),
    )
    op.create_index(
        "ix_optimization_learnings_campaign",
        "optimization_learnings",
        ["campaign_id", "verified_at"],
    )
    op.create_index(
        "ix_optimization_learnings_proposal",
        "optimization_learnings",
        ["proposal_id"],
    )
    op.create_index(
        "ix_optimization_learnings_method",
        "optimization_learnings",
        ["method_id"],
    )

    # ---- monitor_runs ----
    op.create_table(
        "monitor_runs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("campaign_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="completed",
        ),
        sa.Column(
            "engine_summary_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "execution_summary_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "verification_summary_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["campaigns.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_monitor_runs_campaign_status",
        "monitor_runs",
        ["campaign_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_monitor_runs_campaign_status", table_name="monitor_runs")
    op.drop_table("monitor_runs")
    op.drop_index("ix_optimization_learnings_method", table_name="optimization_learnings")
    op.drop_index("ix_optimization_learnings_proposal", table_name="optimization_learnings")
    op.drop_index("ix_optimization_learnings_campaign", table_name="optimization_learnings")
    op.drop_table("optimization_learnings")
