"""[REQ-10009] Retire old external agent worker tables and update deprecated runs/versions

Revision ID: c7d8e9f0a1b2
Revises: b5e6f7a8b9c0
Create Date: 2026-07-22 16:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7d8e9f0a1b2"
down_revision: str | None = "b5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Update old WAITING_EXTERNAL_AGENT runs to CANCELLED
    op.execute(
        "UPDATE ai_capability_runs "
        "SET status = 'CANCELLED', error_code = 'EXTERNAL_WORKER_RETIRED', error_summary = 'Old external worker retired' "
        "WHERE status = 'WAITING_EXTERNAL_AGENT'"
    )

    # 2. Update old WAITING_EXTERNAL_AGENT step executions to CANCELLED
    op.execute(
        "UPDATE ai_step_executions "
        "SET status = 'CANCELLED', error_code = 'EXTERNAL_WORKER_RETIRED', error_summary = 'Old external worker retired' "
        "WHERE status = 'WAITING_EXTERNAL_AGENT'"
    )

    # 3. Clear current_release_version_id pointers if capability version is set to DEPRECATED
    # First set capability versions that required external agent to DEPRECATED
    op.execute(
        "UPDATE ai_capability_versions "
        "SET status = 'DEPRECATED' "
        "WHERE id IN ("
        "  SELECT v.id FROM ai_capability_versions v "
        "  WHERE v.status = 'EXTERNAL_AGENT_REQUIRED'"
        ")"
    )

    # Clear pointers in ai_capabilities
    op.execute(
        "UPDATE ai_capabilities "
        "SET current_published_version_id = NULL "
        "WHERE current_published_version_id IN ("
        "  SELECT id FROM ai_capability_versions WHERE status = 'DEPRECATED'"
        ")"
    )

    # 4. Drop old worker tables in order of foreign key dependency
    op.execute("DROP TABLE IF EXISTS external_agent_result_submissions CASCADE")
    op.execute("DROP TABLE IF EXISTS external_agent_task_leases CASCADE")
    op.execute("DROP TABLE IF EXISTS external_agent_task_attempts CASCADE")
    op.execute("DROP TABLE IF EXISTS external_agent_tasks CASCADE")
    op.execute("DROP TABLE IF EXISTS external_agent_sessions CASCADE")
    op.execute("DROP TABLE IF EXISTS external_agents CASCADE")
    op.execute("DROP TABLE IF EXISTS external_agent_tokens CASCADE")


def downgrade() -> None:
    # 恢复旧表结构与索引占位，确保回滚链 downgrade(base) 能平滑 drop 历史表及索引
    op.execute("CREATE TABLE IF NOT EXISTS external_agent_result_submissions (id UUID PRIMARY KEY)")
    op.execute("CREATE TABLE IF NOT EXISTS external_agent_task_leases (id UUID PRIMARY KEY)")
    op.execute("CREATE TABLE IF NOT EXISTS external_agent_task_attempts (id UUID PRIMARY KEY)")
    op.execute("CREATE TABLE IF NOT EXISTS external_agent_tasks (id UUID PRIMARY KEY)")
    op.execute("CREATE TABLE IF NOT EXISTS external_agent_sessions (id UUID PRIMARY KEY)")
    op.execute("CREATE TABLE IF NOT EXISTS external_agents (id UUID PRIMARY KEY)")
    op.execute(
        "CREATE TABLE IF NOT EXISTS external_agent_tokens (id UUID PRIMARY KEY, token_hash VARCHAR(64))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_external_agent_tokens_token_hash ON external_agent_tokens (token_hash)"
    )
