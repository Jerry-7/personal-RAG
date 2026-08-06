"""Persist Agent routing decisions for observability and replay."""

from alembic import op
import sqlalchemy as sa


revision = "20260806_01"
down_revision = "20260805_01"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("agent_runs")
    }


def upgrade() -> None:
    columns = _columns()
    additions = (
        sa.Column(
            "agent_profile", sa.String(64), nullable=False,
            server_default="standard_research",
        ),
        sa.Column(
            "route_tier", sa.String(16), nullable=False,
            server_default="standard",
        ),
        sa.Column(
            "route_name", sa.String(32), nullable=False,
            server_default="tool_agent",
        ),
        sa.Column("route_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "route_reasons_json", sa.Text(), nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "route_requires_decomposition", sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ),
    )
    for column in additions:
        if column.name not in columns:
            with op.batch_alter_table("agent_runs") as batch:
                batch.add_column(column)


def downgrade() -> None:
    columns = _columns()
    for column_name in (
        "route_requires_decomposition",
        "route_reasons_json",
        "route_score",
        "route_name",
        "route_tier",
        "agent_profile",
    ):
        if column_name in columns:
            with op.batch_alter_table("agent_runs") as batch:
                batch.drop_column(column_name)
