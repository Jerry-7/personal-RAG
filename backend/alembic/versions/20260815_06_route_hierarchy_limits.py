"""Persist route hierarchy limits separately from observed goal-tree shape."""

from alembic import op
import sqlalchemy as sa


revision = "20260815_06"
down_revision = "20260815_05"
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
        if "route_max_children" not in columns:
            batch.add_column(sa.Column(
                "route_max_children", sa.Integer(), nullable=False, server_default="1"
            ))
        if "route_max_depth" not in columns:
            batch.add_column(sa.Column(
                "route_max_depth", sa.Integer(), nullable=False, server_default="1"
            ))

    if "route_tier" in columns:
        op.execute(sa.text("""
            UPDATE agent_runs
            SET route_max_children = CASE route_tier
                    WHEN 'fast' THEN 0
                    WHEN 'expert' THEN 4
                    ELSE 1
                END,
                route_max_depth = CASE route_tier
                    WHEN 'fast' THEN 0
                    WHEN 'expert' THEN 2
                    ELSE 1
                END
        """))


def downgrade() -> None:
    columns = _columns()
    with op.batch_alter_table("agent_runs") as batch:
        if "route_max_depth" in columns:
            batch.drop_column("route_max_depth")
        if "route_max_children" in columns:
            batch.drop_column("route_max_children")
