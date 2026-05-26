"""add_reviewer_notes_to_extracted_clauses

Adds reviewer_notes column to extracted_clauses for Tool A review workflow.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("extracted_clauses", sa.Column("reviewer_notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("extracted_clauses", "reviewer_notes")
