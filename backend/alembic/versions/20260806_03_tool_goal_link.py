"""Link tool executions to their owning Agent goal node."""

from alembic import op
import sqlalchemy as sa


revision = "20260806_03"
down_revision = "20260806_02"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("tool_executions")
    }


def upgrade() -> None:
    if "node_id" not in _columns():
        with op.batch_alter_table("tool_executions") as batch:
            batch.add_column(sa.Column("node_id", sa.String(36), nullable=True))
            batch.create_foreign_key(
                "fk_tool_executions_goal_node",
                "goal_nodes",
                ["node_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch.create_index("ix_tool_executions_node_id", ["node_id"], unique=False)


def downgrade() -> None:
    if "node_id" in _columns():
        with op.batch_alter_table("tool_executions") as batch:
            batch.drop_index("ix_tool_executions_node_id")
            batch.drop_constraint("fk_tool_executions_goal_node", type_="foreignkey")
            batch.drop_column("node_id")
