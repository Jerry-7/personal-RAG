"""Persist one user quality rating for each Agent run."""

from alembic import op
import sqlalchemy as sa


revision = "20260815_07"
down_revision = "20260815_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("agent_run_feedback"):
        return
    op.create_table(
        "agent_run_feedback",
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("rating", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(32), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("agent_run_feedback"):
        op.drop_table("agent_run_feedback")
