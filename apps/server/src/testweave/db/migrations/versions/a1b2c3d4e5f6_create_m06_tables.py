"""[REQ-M06001] create_m06_test_execution_tables

Revision ID: a1b2c3d4e5f6
Revises: 94f27d81a9c1
Create Date: 2026-07-22 10:00:00.000000

新增 M06 测试执行模块数据表：
- execution_task_profiles  执行任务专属信息与高频统计
- execution_cases          固定执行范围用例行（创建后不可变）
- execution_records        追加式执行记录（不可覆盖）
- execution_evidences      执行证据（绑定明确 record）
- export_jobs              Excel 导出任务
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "94f27d81a9c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. execution_task_profiles
    op.create_table(
        "execution_task_profiles",
        sa.Column("execution_task_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("source_design_task_id", sa.UUID(), nullable=False),
        sa.Column("source_requirement_id", sa.UUID(), nullable=False),
        sa.Column("create_idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("test_environment", sa.JSON(), nullable=True),
        sa.Column("build_version", sa.String(length=255), nullable=True),
        sa.Column("scope_frozen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("not_run_count", sa.Integer(), nullable=False),
        sa.Column("passed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("blocked_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("execution_record_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("total_count >= 0", name="ck_exec_profile_total_nonneg"),
        sa.CheckConstraint("not_run_count >= 0", name="ck_exec_profile_notrun_nonneg"),
        sa.CheckConstraint("passed_count >= 0", name="ck_exec_profile_passed_nonneg"),
        sa.CheckConstraint("failed_count >= 0", name="ck_exec_profile_failed_nonneg"),
        sa.CheckConstraint("blocked_count >= 0", name="ck_exec_profile_blocked_nonneg"),
        sa.CheckConstraint("skipped_count >= 0", name="ck_exec_profile_skipped_nonneg"),
        sa.CheckConstraint("execution_record_count >= 0", name="ck_exec_profile_records_nonneg"),
        sa.CheckConstraint(
            "total_count = not_run_count + passed_count + failed_count + blocked_count + skipped_count",
            name="ck_exec_profile_total_sum",
        ),
        sa.ForeignKeyConstraint(
            ["execution_task_id"],
            ["test_tasks.id"],
            name="fk_exec_profile_task_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_exec_profile_project_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_design_task_id"],
            ["test_tasks.id"],
            name="fk_exec_profile_source_task_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_requirement_id"],
            ["requirements.id"],
            name="fk_exec_profile_requirement_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("execution_task_id", name=op.f("pk_execution_task_profiles")),
        sa.UniqueConstraint(
            "project_id",
            "source_design_task_id",
            "create_idempotency_key",
            name="uq_exec_profile_project_source_idemp",
        ),
    )
    op.create_index(
        "ix_execution_task_profiles_project_id", "execution_task_profiles", ["project_id"]
    )

    # 2. execution_cases
    op.create_table(
        "execution_cases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("execution_task_id", sa.UUID(), nullable=False),
        sa.Column("test_case_id", sa.UUID(), nullable=False),
        sa.Column("test_case_revision_id", sa.UUID(), nullable=False),
        sa.Column("case_snapshot", sa.JSON(), nullable=False),
        sa.Column("case_snapshot_hash", sa.String(length=100), nullable=False),
        sa.Column("current_result", sa.String(length=50), nullable=True),
        sa.Column("latest_record_id", sa.UUID(), nullable=True),
        sa.Column("latest_actual_result", sa.Text(), nullable=True),
        sa.Column("latest_note", sa.Text(), nullable=True),
        sa.Column("latest_executed_by", sa.UUID(), nullable=True),
        sa.Column("latest_executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_count", sa.BigInteger(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("scope_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "current_result IS NULL OR current_result IN ('PASSED','FAILED','BLOCKED','SKIPPED')",
            name="ck_exec_cases_result",
        ),
        sa.CheckConstraint("execution_count >= 0", name="ck_exec_cases_count_nonneg"),
        sa.ForeignKeyConstraint(
            ["execution_task_id"],
            ["test_tasks.id"],
            name="fk_exec_cases_task_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_exec_cases_project_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["latest_executed_by"],
            ["users.id"],
            name="fk_exec_cases_latest_executed_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_execution_cases")),
        sa.UniqueConstraint("execution_task_id", "test_case_id", name="uq_exec_cases_task_case"),
        sa.Index("ix_exec_cases_task_current_result", "execution_task_id", "current_result"),
        sa.Index(
            "ix_exec_cases_task_latest_executed_at", "execution_task_id", "latest_executed_at"
        ),
    )
    op.create_index("ix_execution_cases_project_id", "execution_cases", ["project_id"])
    op.create_index("ix_execution_cases_task_id", "execution_cases", ["execution_task_id"])
    op.create_index("ix_execution_cases_test_case_id", "execution_cases", ["test_case_id"])

    # 3. execution_records
    op.create_table(
        "execution_records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("execution_task_id", sa.UUID(), nullable=False),
        sa.Column("execution_case_id", sa.UUID(), nullable=False),
        sa.Column("record_no", sa.Integer(), nullable=False),
        sa.Column("result", sa.String(length=50), nullable=False),
        sa.Column("actual_result", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("reason_code", sa.String(length=50), nullable=True),
        sa.Column("reason_text", sa.Text(), nullable=True),
        sa.Column("executed_by", sa.UUID(), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("build_snapshot", sa.String(length=255), nullable=True),
        sa.Column("environment_snapshot", sa.JSON(), nullable=True),
        sa.Column("record_source", sa.String(length=50), nullable=False),
        sa.Column("correction_of_record_id", sa.UUID(), nullable=True),
        sa.Column("correction_note", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "result IN ('PASSED','FAILED','BLOCKED','SKIPPED')",
            name="ck_exec_records_result",
        ),
        sa.CheckConstraint(
            "record_source IN ('MANUAL','BATCH_PASS','CORRECTION')",
            name="ck_exec_records_source",
        ),
        sa.CheckConstraint("record_no > 0", name="ck_exec_records_no_pos"),
        sa.ForeignKeyConstraint(
            ["execution_task_id"],
            ["test_tasks.id"],
            name="fk_exec_records_task_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["execution_case_id"],
            ["execution_cases.id"],
            name="fk_exec_records_case_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["executed_by"], ["users.id"], name="fk_exec_records_executed_by", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_exec_records_project_id", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_execution_records")),
        sa.UniqueConstraint("execution_case_id", "record_no", name="uq_exec_records_case_no"),
        sa.UniqueConstraint(
            "execution_task_id",
            "executed_by",
            "idempotency_key",
            name="uq_exec_records_task_user_idemp",
        ),
        sa.Index("ix_exec_records_task_executed_at", "execution_task_id", "executed_at"),
        sa.Index("ix_exec_records_executed_by", "executed_by", "executed_at"),
    )
    op.create_index("ix_execution_records_project_id", "execution_records", ["project_id"])
    op.create_index("ix_execution_records_task_id", "execution_records", ["execution_task_id"])
    op.create_index("ix_execution_records_case_id", "execution_records", ["execution_case_id"])

    # 4. execution_evidences
    op.create_table(
        "execution_evidences",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("execution_record_id", sa.UUID(), nullable=False),
        sa.Column("evidence_type", sa.String(length=50), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=True),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "evidence_type IN ('IMAGE','TEXT_LOG','ARCHIVE_LOG','EXTERNAL_LINK')",
            name="ck_exec_evidence_type",
        ),
        sa.ForeignKeyConstraint(
            ["execution_record_id"],
            ["execution_records.id"],
            name="fk_exec_evidences_record_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_exec_evidences_project_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_exec_evidences_created_by", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_execution_evidences")),
    )
    op.create_index("ix_execution_evidences_project_id", "execution_evidences", ["project_id"])
    op.create_index(
        "ix_execution_evidences_record_id", "execution_evidences", ["execution_record_id"]
    )

    # 5. export_jobs
    op.create_table(
        "export_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("resource_type", sa.String(length=50), nullable=False),
        sa.Column("resource_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("scope_snapshot", sa.JSON(), nullable=True),
        sa.Column("file_object_key", sa.String(length=512), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING','RUNNING','COMPLETED','FAILED','EXPIRED')",
            name="ck_export_jobs_status",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_export_jobs_project_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_export_jobs_created_by", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_export_jobs")),
    )
    op.create_index("ix_export_jobs_project_id", "export_jobs", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_export_jobs_project_id", table_name="export_jobs")
    op.drop_table("export_jobs")
    op.drop_index("ix_execution_evidences_record_id", table_name="execution_evidences")
    op.drop_index("ix_execution_evidences_project_id", table_name="execution_evidences")
    op.drop_table("execution_evidences")
    op.drop_index("ix_execution_records_case_id", table_name="execution_records")
    op.drop_index("ix_execution_records_task_id", table_name="execution_records")
    op.drop_index("ix_execution_records_project_id", table_name="execution_records")
    op.drop_table("execution_records")
    op.drop_index("ix_execution_cases_test_case_id", table_name="execution_cases")
    op.drop_index("ix_execution_cases_task_id", table_name="execution_cases")
    op.drop_index("ix_execution_cases_project_id", table_name="execution_cases")
    op.drop_table("execution_cases")
    op.drop_index("ix_execution_task_profiles_project_id", table_name="execution_task_profiles")
    op.drop_table("execution_task_profiles")
