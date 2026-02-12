"""add experiments tables

Revision ID: 0003_experiments
Revises: 0002
Create Date: 2026-02-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0003_experiments"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "experiments",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("campaign_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("experiment_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=True),
        sa.Column("primary_metric", sa.Text(), nullable=False),
        sa.Column("min_sample_conversions", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("min_sample_clicks", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Numeric(), nullable=False, server_default="0.95"),
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
        "ix_experiments_campaign_status", "experiments", ["campaign_id", "status"]
    )

    op.create_table(
        "experiment_variants",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("experiment_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("traffic_share", sa.Numeric(), nullable=False),
        sa.Column("variant_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["experiment_id"], ["experiments.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("experiment_id", "name"),
    )

    op.create_table(
        "experiment_results",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("experiment_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("results_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("analysis_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["experiment_id"], ["experiments.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_experiment_results_experiment_window",
        "experiment_results",
        ["experiment_id", "window_start"],
    )


def downgrade() -> None:
    op.drop_index("ix_experiment_results_experiment_window", table_name="experiment_results")
    op.drop_table("experiment_results")
    op.drop_table("experiment_variants")
    op.drop_index("ix_experiments_campaign_status", table_name="experiments")
    op.drop_table("experiments")
