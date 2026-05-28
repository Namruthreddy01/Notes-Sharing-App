"""add dashboard note categories

Revision ID: b5d6f8a9217d
Revises: a1c112a4608c
Create Date: 2026-05-24 12:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b5d6f8a9217d"
down_revision: Union[str, Sequence[str], None] = "a1c112a4608c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("notes") as batch_op:
        batch_op.add_column(sa.Column("note_department", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("subject_name", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("unit_name", sa.String(length=120), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("notes") as batch_op:
        batch_op.drop_column("unit_name")
        batch_op.drop_column("subject_name")
        batch_op.drop_column("note_department")
