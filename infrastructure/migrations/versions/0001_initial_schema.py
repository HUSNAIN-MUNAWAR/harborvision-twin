"""Initial HarborVision schema.

Revision ID: 0001
Revises: none
"""

from alembic import op
from harborvision import models  # noqa: F401
from harborvision.database import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
