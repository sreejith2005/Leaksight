"""add_contract_refs_for_invoice_and_quantity

Revision ID: e5f6a7b8c9d0
Revises: 62b014537d9f
Create Date: 2026-03-28 17:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "62b014537d9f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("invoice_line_items", sa.Column("contract_ref", sa.Text(), nullable=True))
    op.add_column(
        "contract_line_items",
        sa.Column("contract_quantity", sa.Numeric(precision=20, scale=6), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("contract_line_items", "contract_quantity")
    op.drop_column("invoice_line_items", "contract_ref")
