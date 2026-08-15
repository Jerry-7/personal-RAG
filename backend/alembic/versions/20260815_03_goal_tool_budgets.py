"""Persist the tool-call budget assigned to each Agent goal."""

from alembic import op
import sqlalchemy as sa


revision = "20260815_03"
down_revision = "20260815_02"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("goal_nodes")
    }


def upgrade() -> None:
    if "tool_call_budget" not in _columns():
        with op.batch_alter_table("goal_nodes") as batch:
            batch.add_column(
                sa.Column(
                    "tool_call_budget",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                )
            )
    columns = _columns()
    if {"kind", "agent_profile"}.issubset(columns):
        op.execute(sa.text("""
            UPDATE goal_nodes
            SET tool_call_budget = CASE agent_profile
                WHEN 'fast_general' THEN 2
                WHEN 'standard_research' THEN 5
                WHEN 'expert_supervisor' THEN 10
                WHEN 'local_retriever' THEN 4
                WHEN 'web_researcher' THEN 6
                WHEN 'expert_synthesizer' THEN 3
                ELSE 0
            END
            WHERE kind = 'agent' AND tool_call_budget = 0
        """))


def downgrade() -> None:
    if "tool_call_budget" in _columns():
        with op.batch_alter_table("goal_nodes") as batch:
            batch.drop_column("tool_call_budget")
