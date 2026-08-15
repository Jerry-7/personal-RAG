"""Persist adaptive route classifier evidence on agent runs."""

from alembic import op
import sqlalchemy as sa


revision = "20260815_10"
down_revision = "20260815_09"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("route_decision_source", sa.String(32), "'heuristic'"),
    ("route_confidence", sa.Float(), "1.0"),
    ("route_classifier_model", sa.String(256), "''"),
    ("route_classifier_original_tokens", sa.Integer(), "0"),
    ("route_classifier_compressed_tokens", sa.Integer(), "0"),
    ("route_classifier_calls", sa.Integer(), "0"),
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("agent_runs"):
        return
    existing = {column["name"] for column in inspector.get_columns("agent_runs")}
    source_added = "route_decision_source" not in existing
    for name, column_type, default in _COLUMNS:
        if name not in existing:
            op.add_column(
                "agent_runs",
                sa.Column(
                    name,
                    column_type,
                    nullable=False,
                    server_default=sa.text(default),
                ),
            )
    if source_added:
        op.execute(
            sa.text(
                "UPDATE agent_runs SET route_decision_source = "
                "CASE WHEN route_tier_preference <> 'auto' THEN 'manual' "
                "ELSE 'heuristic' END"
            )
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("agent_runs"):
        return
    existing = {column["name"] for column in inspector.get_columns("agent_runs")}
    for name, _, _ in reversed(_COLUMNS):
        if name in existing:
            op.drop_column("agent_runs", name)
