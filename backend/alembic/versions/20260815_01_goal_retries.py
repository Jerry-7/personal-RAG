"""Persist bounded retry state for Agent goal nodes."""

from alembic import op
import sqlalchemy as sa


revision = "20260815_01"
down_revision = "20260806_03"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("goal_nodes")
    }


def upgrade() -> None:
    columns = _columns()
    additions = (
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"),
    )
    for column in additions:
        if column.name not in columns:
            with op.batch_alter_table("goal_nodes") as batch:
                batch.add_column(column)


def downgrade() -> None:
    columns = _columns()
    for column_name in ("max_attempts", "attempt"):
        if column_name in columns:
            with op.batch_alter_table("goal_nodes") as batch:
                batch.drop_column(column_name)
