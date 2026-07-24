"""REQ-10017 create user_recent_visits table for personal workbench.

Revision ID: b27c10017001
Revises: a16f10016abc
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b27c10017001"
down_revision: str | None = "a16f10016abc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_recent_visits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.String(length=50), nullable=False),
        sa.Column("resource_id", sa.String(length=100), nullable=False),
        sa.Column("visited_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "project_id",
            "resource_type",
            "resource_id",
            name="uq_user_recent_visits_unique",
        ),
    )
    op.create_index(
        "ix_user_recent_visits_user_project_visited",
        "user_recent_visits",
        ["user_id", "project_id", "visited_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_user_recent_visits_user_project_visited", table_name="user_recent_visits")
    op.drop_table("user_recent_visits")
