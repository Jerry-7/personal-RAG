"""Persist per-Agent soft tool repetition guidance."""

from alembic import op
import sqlalchemy as sa


revision = "20260815_11"
down_revision = "20260815_10"
branch_labels = None
depends_on = None


_PROFILE_LIMITS = {
    "fast_general": 1,
    "standard_research": 3,
    "expert_supervisor": 5,
    "local_retriever": 3,
    "web_researcher": 4,
    "expert_synthesizer": 2,
}


def _columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("goal_nodes"):
        return set()
    return {column["name"] for column in inspector.get_columns("goal_nodes")}


def upgrade() -> None:
    columns = _columns()
    if not columns:
        return
    if "tool_repeat_limit" not in columns:
        with op.batch_alter_table("goal_nodes") as batch:
            batch.add_column(
                sa.Column(
                    "tool_repeat_limit",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                )
            )
        columns = _columns()
    if {"kind", "agent_profile", "tool_repeat_limit"}.issubset(columns):
        cases = " ".join(
            f"WHEN '{profile}' THEN {limit}"
            for profile, limit in _PROFILE_LIMITS.items()
        )
        op.execute(sa.text(
            "UPDATE goal_nodes SET tool_repeat_limit = CASE agent_profile "
            f"{cases} ELSE 0 END "
            "WHERE kind = 'agent' AND tool_repeat_limit = 0"
        ))


def downgrade() -> None:
    if "tool_repeat_limit" in _columns():
        with op.batch_alter_table("goal_nodes") as batch:
            batch.drop_column("tool_repeat_limit")
