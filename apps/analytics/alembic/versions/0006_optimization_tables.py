"""add optimization and metrics tables

Revision ID: 0006_optimization_tables
Revises: 0005_execution_tables
Create Date: 2026-02-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0006_optimization_tables"
down_revision = "0005_execution_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- raw_metrics (immutable, insert-only) ----
    op.create_table(
        "raw_metrics",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("campaign_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("metric_name", sa.Text(), nullable=False),
        sa.Column("metric_value", sa.Numeric(), nullable=False),
        sa.Column("metric_unit", sa.Text(), nullable=False, server_default="count"),
        sa.Column("source", sa.Text(), nullable=False, server_default="snapshot"),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=True),
        sa.Column("window_end", sa.Date(), nullable=True),
        sa.Column(
            "metadata_json",
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
        "ix_raw_metrics_campaign_ts",
        "raw_metrics",
        ["campaign_id", "collected_at"],
    )
    op.create_index(
        "ix_raw_metrics_campaign_channel_metric",
        "raw_metrics",
        ["campaign_id", "channel", "metric_name"],
    )

    # ---- derived_kpis ----
    op.create_table(
        "derived_kpis",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("campaign_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("channel", sa.Text(), nullable=True),
        sa.Column("kpi_name", sa.Text(), nullable=False),
        sa.Column("kpi_value", sa.Numeric(), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=True),
        sa.Column("window_end", sa.Date(), nullable=True),
        sa.Column(
            "input_metrics_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["campaigns.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_derived_kpis_campaign_ts",
        "derived_kpis",
        ["campaign_id", "computed_at"],
    )
    op.create_index(
        "ix_derived_kpis_campaign_channel_kpi",
        "derived_kpis",
        ["campaign_id", "channel", "kpi_name"],
    )

    # ---- trend_indicators ----
    op.create_table(
        "trend_indicators",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("campaign_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("channel", sa.Text(), nullable=True),
        sa.Column("kpi_name", sa.Text(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("magnitude", sa.Numeric(), nullable=False),
        sa.Column("period_days", sa.Integer(), nullable=False),
        sa.Column("current_value", sa.Numeric(), nullable=False),
        sa.Column("previous_value", sa.Numeric(), nullable=False),
        sa.Column("confidence", sa.Numeric(), nullable=False, server_default="0"),
        sa.Column(
            "analysis_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["campaigns.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_trend_indicators_campaign_kpi",
        "trend_indicators",
        ["campaign_id", "kpi_name"],
    )

    # ---- optimization_methods ----
    op.create_table(
        "optimization_methods",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("method_type", sa.Text(), nullable=False),
        sa.Column(
            "trigger_conditions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "config_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("cooldown_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column(
            "stats_json",
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # ---- optimization_proposals ----
    op.create_table(
        "optimization_proposals",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("campaign_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("method_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("confidence", sa.Numeric(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("action_type", sa.Text(), nullable=False),
        sa.Column(
            "action_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column(
            "trigger_data_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "guardrail_checks_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "execution_result_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("approved_by", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
            ["method_id"], ["optimization_methods.id"]
        ),
    )
    op.create_index(
        "ix_optimization_proposals_campaign_status",
        "optimization_proposals",
        ["campaign_id", "status"],
    )
    op.create_index(
        "ix_optimization_proposals_method",
        "optimization_proposals",
        ["method_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_optimization_proposals_method",
        table_name="optimization_proposals",
    )
    op.drop_index(
        "ix_optimization_proposals_campaign_status",
        table_name="optimization_proposals",
    )
    op.drop_table("optimization_proposals")
    op.drop_table("optimization_methods")
    op.drop_index(
        "ix_trend_indicators_campaign_kpi",
        table_name="trend_indicators",
    )
    op.drop_table("trend_indicators")
    op.drop_index(
        "ix_derived_kpis_campaign_channel_kpi",
        table_name="derived_kpis",
    )
    op.drop_index(
        "ix_derived_kpis_campaign_ts",
        table_name="derived_kpis",
    )
    op.drop_table("derived_kpis")
    op.drop_index(
        "ix_raw_metrics_campaign_channel_metric",
        table_name="raw_metrics",
    )
    op.drop_index(
        "ix_raw_metrics_campaign_ts",
        table_name="raw_metrics",
    )
    op.drop_table("raw_metrics")
