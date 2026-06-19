"""initial baseline schema

Creates every table declared on Base.metadata (users, usage_events,
churn_scores, action_logs, pipeline_runs). Subsequent schema changes should be
generated incrementally with `alembic revision --autogenerate`.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-19
"""
from alembic import op

from db.database import Base
import db.models  # noqa: F401  (populate Base.metadata)

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
