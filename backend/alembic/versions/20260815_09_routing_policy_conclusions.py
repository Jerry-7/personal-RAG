"""Persist audited human conclusions for routing policy experiments."""

from alembic import op
import sqlalchemy as sa


revision = "20260815_09"
down_revision = "20260815_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("routing_policy_conclusions"):
        return
    op.create_table(
        "routing_policy_conclusions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "policy_version",
            sa.Integer(),
            sa.ForeignKey("routing_policy_versions.version", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("baseline_version", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column(
            "resulting_policy_version",
            sa.Integer(),
            sa.ForeignKey("routing_policy_versions.version", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("note", sa.String(512), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_routing_policy_conclusions_policy_version",
        "routing_policy_conclusions",
        ["policy_version"],
        unique=True,
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("routing_policy_conclusions"):
        op.drop_index(
            "ix_routing_policy_conclusions_policy_version",
            table_name="routing_policy_conclusions",
        )
        op.drop_table("routing_policy_conclusions")
