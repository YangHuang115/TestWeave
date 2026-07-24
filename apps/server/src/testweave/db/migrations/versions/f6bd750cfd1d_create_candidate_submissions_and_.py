"""create_candidate_submissions_and_idempotency_keys_tables

Revision ID: f6bd750cfd1d
Revises: e1f2a3b4c5d6
Create Date: 2026-07-22 22:26:05.781116
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6bd750cfd1d"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_submissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("capability_id", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("submitted_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="SUBMITTED"),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("published_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("auto_published", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
            name=op.f("fk_candidate_submissions_project_id_projects"),
        ),
        sa.ForeignKeyConstraint(
            ["capability_id"],
            ["ai_capabilities.id"],
            ondelete="SET NULL",
            name=op.f("fk_candidate_submissions_capability_id_ai_capabilities"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["test_tasks.id"],
            ondelete="SET NULL",
            name=op.f("fk_candidate_submissions_task_id_test_tasks"),
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by_user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name=op.f("fk_candidate_submissions_submitted_by_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_submissions")),
    )
    op.create_index(
        op.f("ix_candidate_submissions_project_id"),
        "candidate_submissions",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_submissions_capability_id"),
        "candidate_submissions",
        ["capability_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_candidate_submissions_task_id"), "candidate_submissions", ["task_id"], unique=False
    )

    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
            name=op.f("fk_idempotency_keys_project_id_projects"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_idempotency_keys")),
        sa.UniqueConstraint(
            "project_id", "endpoint", "idempotency_key", name=op.f("uq_idempotency_key_proj_ep_key")
        ),
    )
    op.create_index(
        op.f("ix_idempotency_keys_project_id"), "idempotency_keys", ["project_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_idempotency_keys_project_id"), table_name="idempotency_keys")
    op.drop_table("idempotency_keys")
    op.drop_index(op.f("ix_candidate_submissions_task_id"), table_name="candidate_submissions")
    op.drop_index(
        op.f("ix_candidate_submissions_capability_id"), table_name="candidate_submissions"
    )
    op.drop_index(op.f("ix_candidate_submissions_project_id"), table_name="candidate_submissions")
    op.drop_table("candidate_submissions")
