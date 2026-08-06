"""Add persistent goal nodes and ordered run events."""

from alembic import op

from app.db.models import GoalNode, RunEvent


revision = "20260806_02"
down_revision = "20260806_01"
branch_labels = None
depends_on = None


TABLES = (GoalNode.__table__, RunEvent.__table__)


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind, checkfirst=True)
