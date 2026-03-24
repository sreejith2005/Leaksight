"""add_contract_id_to_extracted_line_items

Revision ID: 62b014537d9f
Revises: d4e5f6a7b8c9
Create Date: 2026-03-17 19:26:16.189947

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '62b014537d9f'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('extracted_line_items', sa.Column('contract_id', sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column('extracted_line_items', 'contract_id')
