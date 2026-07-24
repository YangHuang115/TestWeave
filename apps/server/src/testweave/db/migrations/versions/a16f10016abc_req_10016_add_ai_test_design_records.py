"""REQ-10016 add AI test design chain records.

Revision ID: a16f10016abc
Revises: f6bd750cfd1d
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a16f10016abc"
down_revision: str | None = "f6bd750cfd1d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_artifact_set_revisions",
        sa.Column("decision_snapshot", sa.JSON(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_ai_regeneration_requests_run_idempotency",
        "ai_regeneration_requests",
        ["run_id", "idempotency_key"],
    )
    op.create_table(
        "ai_test_design_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("record_no", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column(
            "last_opened_stage",
            sa.String(length=50),
            nullable=False,
            server_default="requirement-analysis",
        ),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("record_no > 0", name="ck_ai_test_design_records_no_positive"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["ai_capability_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id"], ["test_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "task_id",
            "record_no",
            name="uq_ai_test_design_records_project_task_no",
        ),
        sa.UniqueConstraint("run_id", name="uq_ai_test_design_records_run_id"),
        sa.UniqueConstraint(
            "task_id",
            "created_by",
            "idempotency_key",
            name="uq_ai_test_design_records_task_actor_idempotency",
        ),
    )
    op.create_index(
        op.f("ix_ai_test_design_records_project_id"),
        "ai_test_design_records",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_test_design_records_task_id"),
        "ai_test_design_records",
        ["task_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_test_design_records_task_id"), table_name="ai_test_design_records")
    op.drop_index(op.f("ix_ai_test_design_records_project_id"), table_name="ai_test_design_records")
    op.drop_table("ai_test_design_records")
    op.drop_constraint(
        "uq_ai_regeneration_requests_run_idempotency",
        "ai_regeneration_requests",
        type_="unique",
    )
    op.drop_column("ai_artifact_set_revisions", "decision_snapshot")
