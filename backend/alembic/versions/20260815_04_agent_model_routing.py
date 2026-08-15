"""Persist the concrete provider and model selected for each Agent."""

from alembic import op
import sqlalchemy as sa


revision = "20260815_04"
down_revision = "20260815_03"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def upgrade() -> None:
    run_columns = _columns("agent_runs")
    with op.batch_alter_table("agent_runs") as batch:
        if "model_provider" not in run_columns:
            batch.add_column(sa.Column(
                "model_provider", sa.String(32), nullable=False, server_default=""
            ))
        if "model_name" not in run_columns:
            batch.add_column(sa.Column(
                "model_name", sa.String(256), nullable=False, server_default=""
            ))

    goal_columns = _columns("goal_nodes")
    with op.batch_alter_table("goal_nodes") as batch:
        if "model_provider" not in goal_columns:
            batch.add_column(sa.Column(
                "model_provider", sa.String(32), nullable=False, server_default=""
            ))
        if "model_name" not in goal_columns:
            batch.add_column(sa.Column(
                "model_name", sa.String(256), nullable=False, server_default=""
            ))

    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("conversations"):
        op.execute(sa.text("""
            UPDATE agent_runs
            SET model_provider = COALESCE(
                    (SELECT model_provider FROM conversations
                     WHERE conversations.id = agent_runs.conversation_id), ''),
                model_name = COALESCE(
                    (SELECT model_name FROM conversations
                     WHERE conversations.id = agent_runs.conversation_id), '')
            WHERE model_provider = '' OR model_name = ''
        """))
    op.execute(sa.text("""
        UPDATE goal_nodes
        SET model_provider = COALESCE(
                (SELECT model_provider FROM agent_runs
                 WHERE agent_runs.id = goal_nodes.run_id), ''),
            model_name = COALESCE(
                (SELECT model_name FROM agent_runs
                 WHERE agent_runs.id = goal_nodes.run_id), '')
        WHERE model_provider = '' OR model_name = ''
    """))


def downgrade() -> None:
    goal_columns = _columns("goal_nodes")
    with op.batch_alter_table("goal_nodes") as batch:
        if "model_name" in goal_columns:
            batch.drop_column("model_name")
        if "model_provider" in goal_columns:
            batch.drop_column("model_provider")

    run_columns = _columns("agent_runs")
    with op.batch_alter_table("agent_runs") as batch:
        if "model_name" in run_columns:
            batch.drop_column("model_name")
        if "model_provider" in run_columns:
            batch.drop_column("model_provider")
