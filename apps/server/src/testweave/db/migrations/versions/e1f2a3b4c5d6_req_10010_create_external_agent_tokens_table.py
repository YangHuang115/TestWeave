"""[REQ-10010] Create external_agent_tokens table for stateless external gateway

Revision ID: e1f2a3b4c5d6
Revises: c7d8e9f0a1b2
Create Date: 2026-07-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "c7d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_agent_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_prefix", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_external_agent_tokens_created_by_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_external_agent_tokens_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_external_agent_tokens"),
    )
    op.create_index(
        op.f("ix_external_agent_tokens_token_hash"),
        "external_agent_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        op.f("ix_external_agent_tokens_project_id"),
        "external_agent_tokens",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_external_agent_tokens_created_by_user_id"),
        "external_agent_tokens",
        ["created_by_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_external_agent_tokens_created_by_user_id"),
        table_name="external_agent_tokens",
    )
    op.drop_index(
        op.f("ix_external_agent_tokens_project_id"),
        table_name="external_agent_tokens",
    )
    op.drop_index(
        op.f("ix_external_agent_tokens_token_hash"),
        table_name="external_agent_tokens",
    )
    op.drop_table("external_agent_tokens")
