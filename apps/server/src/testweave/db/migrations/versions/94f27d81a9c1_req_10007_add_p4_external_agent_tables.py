"""[REQ-10007] add_p4_external_agent_tables

Revision ID: 94f27d81a9c1
Revises: 80b153ff6bb9
Create Date: 2026-07-22 09:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "94f27d81a9c1"
down_revision: str | None = "80b153ff6bb9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. external_agent_sessions
    op.create_table(
        "external_agent_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("external_agent_id", sa.UUID(), nullable=False),
        sa.Column("token_id", sa.UUID(), nullable=False),
        sa.Column("agent_instance_id", sa.String(length=100), nullable=False),
        sa.Column("session_generation", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("connection_name", sa.String(length=100), nullable=False),
        sa.Column("client_name", sa.String(length=100), nullable=False),
        sa.Column("client_version", sa.String(length=50), nullable=False),
        sa.Column("platform", sa.String(length=50), nullable=False),
        sa.Column("protocol_version", sa.String(length=20), nullable=False),
        sa.Column("supported_protocol_versions", sa.JSON(), nullable=False),
        sa.Column("supported_features", sa.JSON(), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("session_generation > 0", name="ck_ext_agent_sessions_gen_pos"),
        sa.ForeignKeyConstraint(
            ["external_agent_id"],
            ["external_agents.id"],
            name="fk_ext_agent_sessions_agent_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_ext_agent_sessions_project_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["token_id"],
            ["external_agent_tokens.id"],
            name="fk_ext_agent_sessions_token_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_agent_sessions")),
        sa.UniqueConstraint(
            "external_agent_id", "session_generation", name="uq_ext_agent_sessions_agent_gen"
        ),
    )

    # 2. external_agent_tasks
    op.create_table(
        "external_agent_tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("step_execution_id", sa.UUID(), nullable=False),
        sa.Column("regeneration_request_id", sa.UUID(), nullable=True),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("protocol_version", sa.String(length=20), nullable=False),
        sa.Column("context_snapshot_id", sa.UUID(), nullable=False),
        sa.Column("context_generation", sa.Integer(), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("base_revision_set_id", sa.UUID(), nullable=True),
        sa.Column("base_revision_set_hash", sa.String(length=64), nullable=True),
        sa.Column("payload_snapshot", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("fencing_counter", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_auto_retries", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_attempt_id", sa.UUID(), nullable=True),
        sa.Column("result_set_revision_id", sa.UUID(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_summary", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("attempt_count >= 0", name="ck_ext_agent_tasks_attempt_nonneg"),
        sa.CheckConstraint("fencing_counter >= 0", name="ck_ext_agent_tasks_fencing_nonneg"),
        sa.ForeignKeyConstraint(
            ["base_revision_set_id"],
            ["ai_artifact_set_revisions.id"],
            name="fk_ext_agent_tasks_base_set_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["context_snapshot_id"],
            ["ai_context_snapshots.id"],
            name="fk_ext_agent_tasks_ctx_snapshot_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_ext_agent_tasks_project_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["regeneration_request_id"],
            ["ai_regeneration_requests.id"],
            name="fk_ext_agent_tasks_regen_req_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_set_revision_id"],
            ["ai_artifact_set_revisions.id"],
            name="fk_ext_agent_tasks_result_set_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["ai_capability_runs.id"],
            name="fk_ext_agent_tasks_run_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["step_execution_id"],
            ["ai_step_executions.id"],
            name="fk_ext_agent_tasks_step_exec_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_agent_tasks")),
        sa.UniqueConstraint("step_execution_id", name="uq_ext_agent_tasks_step_execution_id"),
    )

    # 3. external_agent_task_attempts
    op.create_table(
        "external_agent_task_attempts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("token_id", sa.UUID(), nullable=False),
        sa.Column("agent_session_id", sa.UUID(), nullable=False),
        sa.Column("agent_session_generation", sa.Integer(), nullable=False),
        sa.Column("claim_idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("claim_request_hash", sa.String(length=64), nullable=False),
        sa.Column("task_package_snapshot", sa.JSON(), nullable=False),
        sa.Column("task_package_hash", sa.String(length=64), nullable=False),
        sa.Column("terminal_action", sa.String(length=32), nullable=True),
        sa.Column("terminal_idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("terminal_request_hash", sa.String(length=64), nullable=True),
        sa.Column("failure_snapshot", sa.JSON(), nullable=True),
        sa.Column("progress_snapshot", sa.JSON(), nullable=True),
        sa.Column("result_set_revision_id", sa.UUID(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_summary", sa.String(length=500), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempt_no > 0", name="ck_ext_agent_attempts_no_pos"),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["external_agents.id"],
            name="fk_ext_agent_attempts_agent_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_session_id"],
            ["external_agent_sessions.id"],
            name="fk_ext_agent_attempts_session_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_ext_agent_attempts_project_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_set_revision_id"],
            ["ai_artifact_set_revisions.id"],
            name="fk_ext_agent_attempts_result_set_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["external_agent_tasks.id"],
            name="fk_ext_agent_attempts_task_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["token_id"],
            ["external_agent_tokens.id"],
            name="fk_ext_agent_attempts_token_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_agent_task_attempts")),
        sa.UniqueConstraint("task_id", "attempt_no", name="uq_ext_agent_attempts_task_attempt_no"),
        sa.UniqueConstraint(
            "task_id", "claim_idempotency_key", name="uq_ext_agent_attempts_claim_idemp"
        ),
    )

    # 4. external_agent_task_leases
    op.create_table(
        "external_agent_task_leases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("attempt_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("token_id", sa.UUID(), nullable=False),
        sa.Column("agent_session_id", sa.UUID(), nullable=False),
        sa.Column("agent_session_generation", sa.Integer(), nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat_sequence", sa.Integer(), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_reason", sa.String(length=100), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("fencing_token > 0", name="ck_ext_agent_leases_fence_pos"),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["external_agents.id"],
            name="fk_ext_agent_leases_agent_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_session_id"],
            ["external_agent_sessions.id"],
            name="fk_ext_agent_leases_session_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["external_agent_task_attempts.id"],
            name="fk_ext_agent_leases_attempt_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_ext_agent_leases_project_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["external_agent_tasks.id"],
            name="fk_ext_agent_leases_task_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["token_id"],
            ["external_agent_tokens.id"],
            name="fk_ext_agent_leases_token_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_agent_task_leases")),
        sa.UniqueConstraint("attempt_id", name="uq_ext_agent_leases_attempt_id"),
        sa.UniqueConstraint("task_id", "fencing_token", name="uq_ext_agent_leases_task_fencing"),
    )

    # 5. external_agent_result_submissions
    op.create_table(
        "external_agent_result_submissions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("attempt_id", sa.UUID(), nullable=False),
        sa.Column("lease_id", sa.UUID(), nullable=False),
        sa.Column("agent_session_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("result_package", sa.JSON(), nullable=False),
        sa.Column("result_package_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("receipt_snapshot", sa.JSON(), nullable=False),
        sa.Column("processing_owner", sa.String(length=100), nullable=True),
        sa.Column("processing_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_version", sa.Integer(), nullable=False),
        sa.Column("result_set_revision_id", sa.UUID(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_summary", sa.String(length=500), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_session_id"],
            ["external_agent_sessions.id"],
            name="fk_ext_agent_submissions_session_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["external_agent_task_attempts.id"],
            name="fk_ext_agent_submissions_attempt_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lease_id"],
            ["external_agent_task_leases.id"],
            name="fk_ext_agent_submissions_lease_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_ext_agent_submissions_project_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_set_revision_id"],
            ["ai_artifact_set_revisions.id"],
            name="fk_ext_agent_submissions_result_set_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["external_agent_tasks.id"],
            name="fk_ext_agent_submissions_task_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_agent_result_submissions")),
        sa.UniqueConstraint(
            "attempt_id", "idempotency_key", name="uq_ext_agent_submissions_attempt_idemp"
        ),
    )


def downgrade() -> None:
    op.drop_table("external_agent_result_submissions")
    op.drop_table("external_agent_task_leases")
    op.drop_table("external_agent_task_attempts")
    op.drop_table("external_agent_tasks")
    op.drop_table("external_agent_sessions")
