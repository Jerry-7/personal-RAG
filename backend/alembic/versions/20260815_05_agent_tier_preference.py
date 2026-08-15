"""Persist the requested Agent tier policy for replay and observability."""

from alembic import op
import sqlalchemy as sa


revision = "20260815_05"
down_revision = "20260815_04"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("agent_runs")
    }


def upgrade() -> None:
    columns = _columns()
    with op.batch_alter_table("agent_runs") as batch:
        if "route_tier_preference" not in columns:
            batch.add_column(sa.Column(
                "route_tier_preference",
                sa.String(16),
                nullable=False,
                server_default="auto",
            ))


def downgrade() -> None:
    columns = _columns()
    with op.batch_alter_table("agent_runs") as batch:
        if "route_tier_preference" in columns:
            batch.drop_column("route_tier_preference")
