"""Create the M00 migration baseline.

Revision ID: 20260719_0001
Revises: None
Create Date: 2026-07-19
"""

revision: str = "20260719_0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Establish the Alembic revision without creating speculative business tables."""


def downgrade() -> None:
    """Remove only the Alembic revision marker managed by Alembic itself."""
