"""[REQ-10001] Add P5 Evaluation, Optimization and Release tables

Revision ID: b5e6f7a8b9c0
Revises: a1b2c3d4e5f6
Create Date: 2026-07-22 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5e6f7a8b9c0"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Update CheckConstraint on ai_capability_runs for run_mode (SQLite & Postgres compatible)
    # 2. Update CheckConstraint on ai_feedbacks for target_type

    # ai_evaluation_sets
    op.create_table(
        "ai_evaluation_sets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("scope_type", sa.String(length=20), nullable=False, server_default="PROJECT"),
        sa.Column("set_key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("current_revision_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope_type IN ('OFFICIAL', 'PROJECT')", name="ck_ai_evaluation_sets_scope_type"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "set_key", name="uq_ai_evaluation_sets_proj_key"),
    )
    op.create_index(
        op.f("ix_ai_evaluation_sets_project_id"), "ai_evaluation_sets", ["project_id"], unique=False
    )

    # ai_evaluation_set_revisions
    op.create_table(
        "ai_evaluation_set_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("set_id", sa.Uuid(), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("revision_hash", sa.String(length=64), nullable=False),
        sa.Column("evaluator_profile_json", sa.JSON(), nullable=False),
        sa.Column("is_frozen", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("case_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["set_id"], ["ai_evaluation_sets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("set_id", "revision_no", name="uq_ai_eval_set_rev_no"),
    )
    op.create_index(
        op.f("ix_ai_evaluation_set_revisions_revision_hash"),
        "ai_evaluation_set_revisions",
        ["revision_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_evaluation_set_revisions_set_id"),
        "ai_evaluation_set_revisions",
        ["set_id"],
        unique=False,
    )

    # ai_evaluation_cases
    op.create_table(
        "ai_evaluation_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("scope_type", sa.String(length=20), nullable=False, server_default="PROJECT"),
        sa.Column("case_key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("current_revision_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope_type IN ('OFFICIAL', 'PROJECT')", name="ck_ai_evaluation_cases_scope_type"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "case_key", name="uq_ai_eval_cases_proj_key"),
    )
    op.create_index(
        op.f("ix_ai_evaluation_cases_project_id"),
        "ai_evaluation_cases",
        ["project_id"],
        unique=False,
    )

    # ai_evaluation_case_revisions
    op.create_table(
        "ai_evaluation_case_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("revision_hash", sa.String(length=64), nullable=False),
        sa.Column("inputs_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("human_decision_fixture_json", sa.JSON(), nullable=True),
        sa.Column("expected_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("declarative_assertions_json", sa.JSON(), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False, server_default="MANUAL"),
        sa.Column("source_ref_id", sa.String(length=100), nullable=True),
        sa.Column(
            "sensitivity", sa.String(length=30), nullable=False, server_default="CONFIDENTIAL"
        ),
        sa.Column("redaction_snapshot_json", sa.JSON(), nullable=True),
        sa.Column(
            "evaluator_key", sa.String(length=100), nullable=False, server_default="declarative_v1"
        ),
        sa.Column("evaluator_version", sa.String(length=50), nullable=False, server_default="1.0"),
        sa.Column("canonical_content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_type IN ('MANUAL', 'OFFICIAL_PACKAGE', 'FEEDBACK_RECOMMENDATION', 'ACCEPTED_REVISION_RECOMMENDATION', 'HISTORICAL_FAILURE')",
            name="ck_ai_eval_case_rev_source_type",
        ),
        sa.CheckConstraint(
            "sensitivity IN ('PUBLIC', 'CONFIDENTIAL', 'REDACTED')",
            name="ck_ai_eval_case_rev_sensitivity",
        ),
        sa.ForeignKeyConstraint(["case_id"], ["ai_evaluation_cases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "revision_no", name="uq_ai_eval_case_rev_no"),
    )
    op.create_index(
        op.f("ix_ai_evaluation_case_revisions_case_id"),
        "ai_evaluation_case_revisions",
        ["case_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_evaluation_case_revisions_revision_hash"),
        "ai_evaluation_case_revisions",
        ["revision_hash"],
        unique=False,
    )

    # ai_evaluation_set_revision_cases
    op.create_table(
        "ai_evaluation_set_revision_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("set_revision_id", sa.Uuid(), nullable=False),
        sa.Column("case_revision_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "weight", sa.Numeric(precision=10, scale=4), nullable=False, server_default="1.0"
        ),
        sa.ForeignKeyConstraint(
            ["case_revision_id"], ["ai_evaluation_case_revisions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["set_revision_id"], ["ai_evaluation_set_revisions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("set_revision_id", "case_revision_id", name="uq_ai_eval_set_rev_case"),
    )
    op.create_index(
        op.f("ix_ai_evaluation_set_revision_cases_case_revision_id"),
        "ai_evaluation_set_revision_cases",
        ["case_revision_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_evaluation_set_revision_cases_set_revision_id"),
        "ai_evaluation_set_revision_cases",
        ["set_revision_id"],
        unique=False,
    )

    # ai_evaluation_case_recommendations
    op.create_table(
        "ai_evaluation_case_recommendations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_id", sa.String(length=100), nullable=False),
        sa.Column("suggested_inputs_json", sa.JSON(), nullable=False),
        sa.Column("suggested_assertions_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="PROPOSED"),
        sa.Column("accepted_case_revision_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_type IN ('FEEDBACK', 'ACCEPTED_REVISION', 'HISTORICAL_FAILURE')",
            name="ck_ai_eval_rec_source_type",
        ),
        sa.CheckConstraint(
            "status IN ('PROPOSED', 'ACCEPTED', 'DISMISSED')", name="ck_ai_eval_rec_status"
        ),
        sa.ForeignKeyConstraint(
            ["accepted_case_revision_id"], ["ai_evaluation_case_revisions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ai_evaluation_case_recommendations_project_id"),
        "ai_evaluation_case_recommendations",
        ["project_id"],
        unique=False,
    )

    # ai_evaluation_runs
    op.create_table(
        "ai_evaluation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("capability_id", sa.Uuid(), nullable=False),
        sa.Column("capability_version_id", sa.Uuid(), nullable=False),
        sa.Column("package_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("set_revision_id", sa.Uuid(), nullable=False),
        sa.Column("set_revision_hash", sa.String(length=64), nullable=False),
        sa.Column("evaluator_profile_hash", sa.String(length=64), nullable=False),
        sa.Column("runtime_profile_hash", sa.String(length=64), nullable=False),
        sa.Column("model_provider", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("model_parameters_json", sa.JSON(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("seed_supported", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="PENDING"),
        sa.Column("total_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pricing_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("release_policy_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'PARTIAL', 'FAILED', 'BLOCKED', 'CANCELLED')",
            name="ck_ai_evaluation_runs_status",
        ),
        sa.ForeignKeyConstraint(["capability_id"], ["ai_capabilities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["capability_version_id"], ["ai_capability_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["set_revision_id"], ["ai_evaluation_set_revisions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ai_evaluation_runs_capability_id"),
        "ai_evaluation_runs",
        ["capability_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_evaluation_runs_capability_version_id"),
        "ai_evaluation_runs",
        ["capability_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_evaluation_runs_project_id"), "ai_evaluation_runs", ["project_id"], unique=False
    )
    op.create_index(
        op.f("ix_ai_evaluation_runs_set_revision_id"),
        "ai_evaluation_runs",
        ["set_revision_id"],
        unique=False,
    )

    # ai_evaluation_results
    op.create_table(
        "ai_evaluation_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_run_id", sa.Uuid(), nullable=False),
        sa.Column("case_revision_id", sa.Uuid(), nullable=False),
        sa.Column("repetition_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("capability_run_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="PENDING"),
        sa.Column("assertions_passed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("assertions_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(precision=14, scale=6), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("evidence_summary_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'PASSED', 'FAILED', 'ERROR', 'BLOCKED', 'SKIPPED', 'CANCELLED')",
            name="ck_ai_evaluation_results_status",
        ),
        sa.ForeignKeyConstraint(
            ["capability_run_id"], ["ai_capability_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["case_revision_id"], ["ai_evaluation_case_revisions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_run_id"], ["ai_evaluation_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evaluation_run_id",
            "case_revision_id",
            "repetition_index",
            name="uq_ai_eval_result_case_rep",
        ),
    )
    op.create_index(
        op.f("ix_ai_evaluation_results_case_revision_id"),
        "ai_evaluation_results",
        ["case_revision_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_evaluation_results_evaluation_run_id"),
        "ai_evaluation_results",
        ["evaluation_run_id"],
        unique=False,
    )

    # ai_evaluation_metric_results
    op.create_table(
        "ai_evaluation_metric_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_run_id", sa.Uuid(), nullable=False),
        sa.Column("metric_key", sa.String(length=100), nullable=False),
        sa.Column("evaluator_key", sa.String(length=100), nullable=False),
        sa.Column("evaluator_version", sa.String(length=50), nullable=False),
        sa.Column("data_source", sa.String(length=50), nullable=False),
        sa.Column("numerator", sa.Numeric(precision=16, scale=6), nullable=True),
        sa.Column("denominator", sa.Numeric(precision=16, scale=6), nullable=True),
        sa.Column("value", sa.Numeric(precision=16, scale=6), nullable=True),
        sa.Column("unit", sa.String(length=30), nullable=True),
        sa.Column(
            "direction", sa.String(length=30), nullable=False, server_default="HIGHER_IS_BETTER"
        ),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
        sa.Column("evaluator_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "direction IN ('HIGHER_IS_BETTER', 'LOWER_IS_BETTER')",
            name="ck_ai_eval_metric_direction",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_run_id"], ["ai_evaluation_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evaluation_run_id", "metric_key", name="uq_ai_eval_metric_key"),
    )
    op.create_index(
        op.f("ix_ai_evaluation_metric_results_evaluation_run_id"),
        "ai_evaluation_metric_results",
        ["evaluation_run_id"],
        unique=False,
    )

    # ai_evaluation_comparisons
    op.create_table(
        "ai_evaluation_comparisons",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("capability_id", sa.Uuid(), nullable=False),
        sa.Column("baseline_run_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_run_id", sa.Uuid(), nullable=False),
        sa.Column("baseline_version_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_version_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="PENDING"),
        sa.Column("not_comparable_reason", sa.String(length=100), nullable=True),
        sa.Column("summary_diff_json", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING', 'READY', 'NOT_COMPARABLE', 'FAILED')",
            name="ck_ai_eval_comparison_status",
        ),
        sa.ForeignKeyConstraint(["baseline_run_id"], ["ai_evaluation_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["baseline_version_id"], ["ai_capability_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_run_id"], ["ai_evaluation_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_version_id"], ["ai_capability_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["capability_id"], ["ai_capabilities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "baseline_run_id", "candidate_run_id", name="uq_ai_eval_comparison_pair"
        ),
    )
    op.create_index(
        op.f("ix_ai_evaluation_comparisons_baseline_run_id"),
        "ai_evaluation_comparisons",
        ["baseline_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_evaluation_comparisons_candidate_run_id"),
        "ai_evaluation_comparisons",
        ["candidate_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_evaluation_comparisons_capability_id"),
        "ai_evaluation_comparisons",
        ["capability_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_evaluation_comparisons_project_id"),
        "ai_evaluation_comparisons",
        ["project_id"],
        unique=False,
    )

    # ai_evaluation_comparison_items
    op.create_table(
        "ai_evaluation_comparison_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("comparison_id", sa.Uuid(), nullable=False),
        sa.Column("case_revision_id", sa.Uuid(), nullable=False),
        sa.Column("repetition_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("baseline_result_id", sa.Uuid(), nullable=True),
        sa.Column("candidate_result_id", sa.Uuid(), nullable=True),
        sa.Column("baseline_status", sa.String(length=30), nullable=True),
        sa.Column("candidate_status", sa.String(length=30), nullable=True),
        sa.Column("delta_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["baseline_result_id"], ["ai_evaluation_results.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_result_id"], ["ai_evaluation_results.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["case_revision_id"], ["ai_evaluation_case_revisions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["comparison_id"], ["ai_evaluation_comparisons.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "comparison_id",
            "case_revision_id",
            "repetition_index",
            name="uq_ai_eval_comp_item_pair",
        ),
    )
    op.create_index(
        op.f("ix_ai_evaluation_comparison_items_case_revision_id"),
        "ai_evaluation_comparison_items",
        ["case_revision_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_evaluation_comparison_items_comparison_id"),
        "ai_evaluation_comparison_items",
        ["comparison_id"],
        unique=False,
    )

    # ai_quality_observation_snapshots
    op.create_table(
        "ai_quality_observation_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("capability_id", sa.Uuid(), nullable=False),
        sa.Column("time_window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("time_window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("normal_run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("review_coverage", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("human_acceptance", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("accepted_after_edit", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("regeneration_rate", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("failure_rate", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("duration_p50_ms", sa.Integer(), nullable=True),
        sa.Column("duration_p95_ms", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("total_cost", sa.Numeric(precision=14, scale=6), nullable=True),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["capability_id"], ["ai_capabilities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ai_quality_observation_snapshots_capability_id"),
        "ai_quality_observation_snapshots",
        ["capability_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_quality_observation_snapshots_project_id"),
        "ai_quality_observation_snapshots",
        ["project_id"],
        unique=False,
    )

    # ai_optimization_suggestions
    op.create_table(
        "ai_optimization_suggestions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("capability_id", sa.Uuid(), nullable=False),
        sa.Column("suggestion_type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence_manifest_json", sa.JSON(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("time_window_json", sa.JSON(), nullable=True),
        sa.Column("impacted_cases_json", sa.JSON(), nullable=True),
        sa.Column("suggested_action_area", sa.String(length=100), nullable=False),
        sa.Column("risk_assessment", sa.Text(), nullable=False),
        sa.Column("uncertainty_note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="OPEN"),
        sa.Column("resolved_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "suggestion_type IN ('PROMPT', 'SCHEMA', 'WORKFLOW', 'VALIDATOR', 'MODEL_POLICY', 'EVALUATION_CASE', 'DOCUMENTATION')",
            name="ck_ai_opt_suggestion_type",
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'PACKAGED', 'DISMISSED', 'RESOLVED')",
            name="ck_ai_opt_suggestion_status",
        ),
        sa.ForeignKeyConstraint(["capability_id"], ["ai_capabilities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["resolved_version_id"], ["ai_capability_versions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ai_optimization_suggestions_capability_id"),
        "ai_optimization_suggestions",
        ["capability_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_optimization_suggestions_project_id"),
        "ai_optimization_suggestions",
        ["project_id"],
        unique=False,
    )

    # ai_workspace_packages
    op.create_table(
        "ai_workspace_packages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("capability_id", sa.Uuid(), nullable=False),
        sa.Column("package_type", sa.String(length=30), nullable=False),
        sa.Column("package_hash", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=30), nullable=False, server_default="1.0"),
        sa.Column("base_version_id", sa.Uuid(), nullable=True),
        sa.Column("candidate_version_id", sa.Uuid(), nullable=True),
        sa.Column("base_package_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("evaluation_set_revision_id", sa.Uuid(), nullable=True),
        sa.Column("suggestion_ids_json", sa.JSON(), nullable=True),
        sa.Column("evidence_manifest_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="READY"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "package_type IN ('FEEDBACK', 'EVALUATION', 'OPTIMIZATION')",
            name="ck_ai_ws_package_type",
        ),
        sa.CheckConstraint(
            "status IN ('READY', 'REVOKED', 'EXPIRED', 'SUPERSEDED')",
            name="ck_ai_ws_package_status",
        ),
        sa.ForeignKeyConstraint(
            ["base_version_id"], ["ai_capability_versions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_version_id"], ["ai_capability_versions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["capability_id"], ["ai_capabilities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["evaluation_set_revision_id"], ["ai_evaluation_set_revisions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ai_workspace_packages_capability_id"),
        "ai_workspace_packages",
        ["capability_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_workspace_packages_package_hash"),
        "ai_workspace_packages",
        ["package_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_workspace_packages_project_id"),
        "ai_workspace_packages",
        ["project_id"],
        unique=False,
    )

    # ai_capability_release_requests
    op.create_table(
        "ai_capability_release_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("capability_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_version_id", sa.Uuid(), nullable=False),
        sa.Column("base_version_id", sa.Uuid(), nullable=True),
        sa.Column("package_fingerprints_json", sa.JSON(), nullable=False),
        sa.Column("evaluation_run_id", sa.Uuid(), nullable=True),
        sa.Column("comparison_id", sa.Uuid(), nullable=True),
        sa.Column("config_diff_json", sa.JSON(), nullable=True),
        sa.Column("blocking_checks_json", sa.JSON(), nullable=False),
        sa.Column("advisories_json", sa.JSON(), nullable=False),
        sa.Column("policy_provider_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("rollback_target_version_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="DRAFT"),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'VALIDATING', 'IN_REVIEW', 'APPROVED', 'REJECTED', 'CANCELLED', 'RELEASED')",
            name="ck_ai_rel_req_status",
        ),
        sa.ForeignKeyConstraint(
            ["base_version_id"], ["ai_capability_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_version_id"], ["ai_capability_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["capability_id"], ["ai_capabilities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["comparison_id"], ["ai_evaluation_comparisons.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_run_id"], ["ai_evaluation_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["rollback_target_version_id"], ["ai_capability_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ai_capability_release_requests_capability_id"),
        "ai_capability_release_requests",
        ["capability_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_capability_release_requests_project_id"),
        "ai_capability_release_requests",
        ["project_id"],
        unique=False,
    )

    # ai_capability_deployments
    op.create_table(
        "ai_capability_deployments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("capability_id", sa.Uuid(), nullable=False),
        sa.Column("stable_version_id", sa.Uuid(), nullable=False),
        sa.Column("canary_version_id", sa.Uuid(), nullable=True),
        sa.Column("canary_basis_points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("routing_salt", sa.String(length=64), nullable=False),
        sa.Column("deployment_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="ACTIVE"),
        sa.Column("active_release_request_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "canary_basis_points >= 0 AND canary_basis_points <= 10000",
            name="ck_ai_deploy_canary_bp",
        ),
        sa.CheckConstraint("status IN ('ACTIVE', 'DISABLED')", name="ck_ai_deploy_status"),
        sa.ForeignKeyConstraint(
            ["active_release_request_id"],
            ["ai_capability_release_requests.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["canary_version_id"], ["ai_capability_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["capability_id"], ["ai_capabilities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["stable_version_id"], ["ai_capability_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("capability_id"),
    )
    op.create_index(
        op.f("ix_ai_capability_deployments_capability_id"),
        "ai_capability_deployments",
        ["capability_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_ai_capability_deployments_project_id"),
        "ai_capability_deployments",
        ["project_id"],
        unique=False,
    )

    # ai_capability_release_actions
    op.create_table(
        "ai_capability_release_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("capability_id", sa.Uuid(), nullable=False),
        sa.Column("deployment_id", sa.Uuid(), nullable=False),
        sa.Column("release_request_id", sa.Uuid(), nullable=True),
        sa.Column("action_type", sa.String(length=50), nullable=False),
        sa.Column("stable_version_id", sa.Uuid(), nullable=False),
        sa.Column("canary_version_id", sa.Uuid(), nullable=True),
        sa.Column("canary_basis_points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deployment_revision", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action_type IN ('FULL_RELEASE', 'START_CANARY', 'ADJUST_CANARY', 'PROMOTE_CANARY', 'ROLLBACK')",
            name="ck_ai_rel_action_type",
        ),
        sa.CheckConstraint(
            "canary_basis_points >= 0 AND canary_basis_points <= 10000",
            name="ck_ai_rel_action_canary_bp",
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["canary_version_id"], ["ai_capability_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["capability_id"], ["ai_capabilities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["deployment_id"], ["ai_capability_deployments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["release_request_id"], ["ai_capability_release_requests.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["stable_version_id"], ["ai_capability_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ai_capability_release_actions_capability_id"),
        "ai_capability_release_actions",
        ["capability_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_capability_release_actions_deployment_id"),
        "ai_capability_release_actions",
        ["deployment_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("ai_capability_release_actions")
    op.drop_table("ai_capability_deployments")
    op.drop_table("ai_capability_release_requests")
    op.drop_table("ai_workspace_packages")
    op.drop_table("ai_optimization_suggestions")
    op.drop_table("ai_quality_observation_snapshots")
    op.drop_table("ai_evaluation_comparison_items")
    op.drop_table("ai_evaluation_comparisons")
    op.drop_table("ai_evaluation_metric_results")
    op.drop_table("ai_evaluation_results")
    op.drop_table("ai_evaluation_runs")
    op.drop_table("ai_evaluation_case_recommendations")
    op.drop_table("ai_evaluation_set_revision_cases")
    op.drop_table("ai_evaluation_case_revisions")
    op.drop_table("ai_evaluation_cases")
    op.drop_table("ai_evaluation_set_revisions")
    op.drop_table("ai_evaluation_sets")
