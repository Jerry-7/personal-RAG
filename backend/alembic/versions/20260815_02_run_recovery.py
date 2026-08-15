"""Link retried Agent runs to their interrupted or failed source run."""

from alembic import op
import sqlalchemy as sa


revision = "20260815_02"
down_revision = "20260815_01"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("agent_runs")
    }


def upgrade() -> None:
    if "retry_of_run_id" not in _columns():
        with op.batch_alter_table("agent_runs") as batch:
            batch.add_column(sa.Column("retry_of_run_id", sa.String(36), nullable=True))
            batch.create_foreign_key(
                "fk_agent_runs_retry_source",
                "agent_runs",
                ["retry_of_run_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch.create_index(
                "ix_agent_runs_retry_of_run_id",
                ["retry_of_run_id"],
                unique=False,
            )


def downgrade() -> None:
    if "retry_of_run_id" in _columns():
        with op.batch_alter_table("agent_runs") as batch:
            batch.drop_index("ix_agent_runs_retry_of_run_id")
            batch.drop_constraint("fk_agent_runs_retry_source", type_="foreignkey")
            batch.drop_column("retry_of_run_id")
