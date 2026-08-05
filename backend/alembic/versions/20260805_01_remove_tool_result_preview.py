"""Remove unused tool result previews from the audit log."""

from alembic import op
import sqlalchemy as sa


revision = "20260805_01"
down_revision = "20260731_01"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("tool_executions")
    }


def upgrade() -> None:
    if "result_preview" in _columns():
        with op.batch_alter_table("tool_executions") as batch:
            batch.drop_column("result_preview")


def downgrade() -> None:
    if "result_preview" not in _columns():
        with op.batch_alter_table("tool_executions") as batch:
            batch.add_column(sa.Column("result_preview", sa.Text(), nullable=True))
