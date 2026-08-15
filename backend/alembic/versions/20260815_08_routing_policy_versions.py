"""Persist versioned routing thresholds and their use by Agent runs."""

from alembic import op
import sqlalchemy as sa


revision = "20260815_08"
down_revision = "20260815_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("routing_policy_versions"):
        op.create_table(
            "routing_policy_versions",
            sa.Column("version", sa.Integer(), primary_key=True),
            sa.Column("standard_min_score", sa.Integer(), nullable=False),
            sa.Column("expert_min_score", sa.Integer(), nullable=False),
            sa.Column("source", sa.String(32), nullable=False),
            sa.Column("based_on_version", sa.Integer(), nullable=True),
            sa.Column("note", sa.String(512), nullable=True),
            sa.Column(
                "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
            sa.Column(
                "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
            ),
        )
        op.create_index(
            "ix_routing_policy_versions_is_active",
            "routing_policy_versions",
            ["is_active"],
        )
        op.create_index(
            "uq_routing_policy_versions_active",
            "routing_policy_versions",
            ["is_active"],
            unique=True,
            sqlite_where=sa.text("is_active = 1"),
        )
    run_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("agent_runs")
    }
    if "route_policy_version" not in run_columns:
        op.add_column(
            "agent_runs",
            sa.Column(
                "route_policy_version",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("agent_runs"):
        run_columns = {
            column["name"] for column in inspector.get_columns("agent_runs")
        }
        if "route_policy_version" in run_columns:
            op.drop_column("agent_runs", "route_policy_version")
    if inspector.has_table("routing_policy_versions"):
        op.drop_index(
            "uq_routing_policy_versions_active",
            table_name="routing_policy_versions",
        )
        op.drop_index(
            "ix_routing_policy_versions_is_active",
            table_name="routing_policy_versions",
        )
        op.drop_table("routing_policy_versions")
