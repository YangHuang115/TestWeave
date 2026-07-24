import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    UUID,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from testweave.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)
    is_system_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    # Relationships
    sessions: Mapped[list["UserSession"]] = relationship(
        "UserSession", back_populates="user", cascade="all, delete-orphan"
    )
    memberships: Mapped[list["ProjectMember"]] = relationship(
        "ProjectMember", back_populates="user", cascade="all, delete-orphan"
    )


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="sessions")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC", nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    # Relationships
    members: Mapped[list["ProjectMember"]] = relationship(
        "ProjectMember", back_populates="project", cascade="all, delete-orphan"
    )


class ProjectMember(Base):
    __tablename__ = "project_members"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[str] = mapped_column(String(50), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="members")
    user: Mapped["User"] = relationship("User", back_populates="memberships")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    object_type: Mapped[str] = mapped_column(String(100), nullable=False)
    object_id: Mapped[str] = mapped_column(String(100), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class Version(Base):
    __tablename__ = "versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(50), nullable=False)
    key_normalized: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="PLANNING", nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    planned_start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    planned_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    previous_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("project_id", "key_normalized", name="uq_versions_project_key"),
    )


class Requirement(Base):
    __tablename__ = "requirements"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requirement_no: Mapped[str] = mapped_column(String(100), nullable=False)
    requirement_no_normalized: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    acceptance_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(50), default="MEDIUM", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="DRAFT", nullable=False)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    tags_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "project_id", "requirement_no_normalized", name="uq_requirements_project_no"
        ),
    )


class VersionRequirement(Base):
    __tablename__ = "version_requirements"

    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("versions.id", ondelete="CASCADE"), primary_key=True
    )
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("requirements.id", ondelete="CASCADE"), primary_key=True
    )
    linked_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RequirementAttachment(Base):
    __tablename__ = "requirement_attachments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="ACTIVE", nullable=False)
    referenced_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    archived_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CodeRepository(Base):
    __tablename__ = "code_repositories"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    repository_type: Mapped[str] = mapped_column(String(50), default="GIT", nullable=False)
    provider_type: Mapped[str] = mapped_column(String(50), default="GENERIC", nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    remote_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    auth_type: Mapped[str] = mapped_column(String(50), default="NONE", nullable=False)
    credential_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    main_branch: Mapped[str] = mapped_column(String(100), default="main", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sync_status: Mapped[str] = mapped_column(String(50), default="NOT_SYNCED", nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_head_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class GitCommit(Base):
    __tablename__ = "git_commits"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("code_repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sha: Mapped[str] = mapped_column(String(40), nullable=False)
    author_name: Mapped[str] = mapped_column(String(100), nullable=False)
    author_email: Mapped[str] = mapped_column(String(255), nullable=False)
    committer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    committer_email: Mapped[str] = mapped_column(String(255), nullable=False)
    authored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    parent_shas_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    is_merge: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_reachable_from_main: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    files_changed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    additions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deletions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (UniqueConstraint("repository_id", "sha", name="uq_git_commits_repo_sha"),)


class GitCommitFile(Base):
    __tablename__ = "git_commit_files"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    commit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("git_commits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    old_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_path: Mapped[str] = mapped_column(Text, nullable=False)
    change_type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_binary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    additions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deletions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    patch_storage_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    patch_size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    patch_truncated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class RequirementCommitLink(Base):
    __tablename__ = "requirement_commit_links"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    commit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("git_commits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    matched_requirement_no: Mapped[str] = mapped_column(String(100), nullable=False)
    match_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    match_method: Mapped[str] = mapped_column(
        String(50), default="COMMIT_MESSAGE_EXACT_TOKEN", nullable=False
    )
    status: Mapped[str] = mapped_column(String(50), default="ACTIVE", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    staled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "requirement_id", "commit_id", "match_revision", name="uq_req_commit_link"
        ),
    )


class RepositorySyncJob(Base):
    __tablename__ = "repository_sync_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    repository_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("code_repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="PENDING", nullable=False)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("requirements.id", ondelete="CASCADE"), nullable=True
    )
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    lease_owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class TestTask(Base):
    __tablename__ = "test_tasks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_no: Mapped[str] = mapped_column(String(100), nullable=False)
    task_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # CASE_DESIGN / TEST_EXECUTION
    status: Mapped[str] = mapped_column(String(50), default="DRAFT", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(50), default="MEDIUM", nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    planned_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    planned_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actual_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completion_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    excluded_scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    previous_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("project_id", "task_no", name="uq_test_tasks_project_task_no"),
    )


class TestTaskRequirement(Base):
    __tablename__ = "test_task_requirements"

    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("test_tasks.id", ondelete="CASCADE"), primary_key=True
    )
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("requirements.id", ondelete="CASCADE"), primary_key=True
    )
    linked_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (UniqueConstraint("task_id", name="uq_test_task_requirements_task_id"),)


class TestTaskParticipant(Base):
    __tablename__ = "test_task_participants"

    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("test_tasks.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class TestTaskStatusHistory(Base):
    __tablename__ = "test_task_status_history"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("test_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_status: Mapped[str] = mapped_column(String(50), nullable=False)
    to_status: Mapped[str] = mapped_column(String(50), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reason_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    request_id: Mapped[str] = mapped_column(String(100), nullable=False)


class TestTaskBlockage(Base):
    __tablename__ = "test_task_blockages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("test_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reason_code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    blocked_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    blocked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class TestCase(Base):
    __tablename__ = "test_cases"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_no: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    precondition: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(50), default="MEDIUM", nullable=False)
    case_type: Mapped[str] = mapped_column(String(50), default="FUNCTIONAL", nullable=False)
    tags_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    test_data_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_task_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("test_tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    row_version: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("project_id", "case_no", name="uq_test_cases_project_case_no"),
    )


class TestCaseStep(Base):
    __tablename__ = "test_case_steps"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    expected_result: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("case_id", "step_order", name="uq_test_case_steps_case_step_order"),
    )


class CaseModule(Base):
    __tablename__ = "case_modules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("case_modules.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "project_id", "parent_id", "name", name="uq_case_modules_project_parent_name"
        ),
    )


class TestCaseModuleRelation(Base):
    __tablename__ = "test_case_module_relations"

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("test_cases.id", ondelete="CASCADE"), primary_key=True
    )
    module_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("case_modules.id", ondelete="CASCADE"), primary_key=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class TestCaseRevision(Base):
    __tablename__ = "test_case_revisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    change_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    edit_session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("case_id", "revision_no", name="uq_test_case_revisions_case_revision_no"),
    )


class TestCaseEditSession(Base):
    __tablename__ = "test_case_edit_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    base_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("test_case_revisions.id", ondelete="SET NULL"), nullable=True
    )
    base_row_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="OPEN", nullable=False)
    dirty_fields: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CaseNumberSequence(Base):
    __tablename__ = "case_number_sequences"

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    current_value: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class TestCaseMindmap(Base):
    __tablename__ = "test_case_mindmaps"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("test_tasks.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


# ----------------------------------------------------------------------
# M09 AI Capability Center Models
# ----------------------------------------------------------------------


class AICapability(Base):
    """AI 能力实体表。"""

    __tablename__ = "ai_capabilities"
    __table_args__ = (
        UniqueConstraint("namespace", "code", name="uq_ai_capabilities_namespace_code"),
        CheckConstraint(
            "scope IN ('OFFICIAL', 'PROJECT')",
            name="ck_ai_capabilities_scope_values",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'ARCHIVED')",
            name="ck_ai_capabilities_status_values",
        ),
        CheckConstraint(
            "(scope = 'OFFICIAL' AND project_id IS NULL) OR (scope = 'PROJECT' AND project_id IS NOT NULL)",
            name="ck_ai_capabilities_scope_project_nullability",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    namespace: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="OFFICIAL")
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "projects.id", ondelete="RESTRICT", name="fk_ai_capabilities_project_id_projects"
        ),
        nullable=True,
    )
    current_published_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_capability_versions.id",
            ondelete="RESTRICT",
            name="fk_ai_capabilities_curr_ver_id",
            use_alter=True,
        ),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    project: Mapped["Project | None"] = relationship()
    current_published_version: Mapped["AICapabilityVersion | None"] = relationship(
        foreign_keys=[current_published_version_id],
        post_update=True,
    )


class AICapabilityVersion(Base):
    """AI 能力版本历史实体表。"""

    __tablename__ = "ai_capability_versions"
    __table_args__ = (
        UniqueConstraint(
            "capability_id", "version", name="uq_ai_capability_versions_capability_version"
        ),
        CheckConstraint(
            "status IN ('SYNCED_DRAFT', 'VALIDATING', 'IN_REVIEW', 'PUBLISHED', 'REJECTED', 'DEPRECATED', 'ROLLED_BACK')",
            name="ck_ai_capability_versions_status_values",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    capability_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_capabilities.id",
            ondelete="RESTRICT",
            name="fk_ai_capability_versions_capability_id_ai_capabilities",
        ),
        nullable=False,
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="SYNCED_DRAFT")
    package_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    compatibility_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    workflow_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    input_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_source: Mapped[str] = mapped_column(String(50), nullable=False, default="GATEWAY_SYNC")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id", ondelete="SET NULL", name="fk_ai_capability_versions_created_by_users"
        ),
        nullable=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    capability: Mapped["AICapability"] = relationship(foreign_keys=[capability_id])
    creator: Mapped["User | None"] = relationship()


class AICapabilityRun(Base):
    """AI 能力运行记录实体表。"""

    __tablename__ = "ai_capability_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'WAITING_HUMAN', 'WAITING_EXTERNAL_AGENT', 'WAITING_RETRY', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="ck_ai_capability_runs_status_values",
        ),
        CheckConstraint(
            "next_event_sequence >= 0", name="ck_ai_capability_runs_next_event_sequence_nonnegative"
        ),
        UniqueConstraint(
            "project_id",
            "initiator_id",
            "idempotency_key",
            name="uq_ai_capability_runs_proj_init_idempotency",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    capability_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_capability_versions.id",
            ondelete="RESTRICT",
            name="fk_ai_capability_runs_capability_version_id",
        ),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "projects.id", ondelete="RESTRICT", name="fk_ai_capability_runs_project_id_projects"
        ),
        nullable=False,
    )
    initiator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id", ondelete="SET NULL", name="fk_ai_capability_runs_initiator_id_users"
        ),
        nullable=True,
    )
    trace_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    run_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="NORMAL")
    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    execution_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    execution_snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    next_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id", ondelete="SET NULL", name="fk_ai_capability_runs_cancel_requested_by_users"
        ),
        nullable=True,
    )
    final_output_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    usage_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    capability_version: Mapped["AICapabilityVersion"] = relationship()
    project: Mapped["Project"] = relationship()
    initiator: Mapped["User | None"] = relationship(foreign_keys=[initiator_id])
    cancel_requested_by_user: Mapped["User | None"] = relationship(
        foreign_keys=[cancel_requested_by]
    )


class AIStepExecution(Base):
    """AI 步骤执行记录实体表。"""

    __tablename__ = "ai_step_executions"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "node_id", "attempt", name="uq_ai_step_executions_run_node_attempt"
        ),
        CheckConstraint("attempt > 0", name="ck_ai_step_executions_attempt_positive"),
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'WAITING_HUMAN', 'WAITING_EXTERNAL_AGENT', 'WAITING_RETRY', 'SUCCEEDED', 'FAILED', 'CANCELLED', 'SKIPPED')",
            name="ck_ai_step_executions_status_values",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_capability_runs.id",
            ondelete="RESTRICT",
            name="fk_ai_step_executions_run_id_ai_capability_runs",
        ),
        nullable=False,
    )
    node_id: Mapped[str] = mapped_column(String(100), nullable=False)
    node_type: Mapped[str] = mapped_column(String(50), nullable=False, default="SKILL")
    node_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    input_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    input_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    input_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    available_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    claim_owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    claim_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    claim_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_step_executions.id", ondelete="SET NULL", name="fk_ai_step_executions_retry_of_id"
        ),
        nullable=True,
    )
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    safety_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    provider_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    usage_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    input_context_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    output_revision_set_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    execution_reason: Mapped[str] = mapped_column(String(32), nullable=False, default="NORMAL")
    context_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    run: Mapped["AICapabilityRun"] = relationship()


class AIRunEvent(Base):
    """AI Run 持久化事件记录表。"""

    __tablename__ = "ai_run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_ai_run_events_run_sequence"),
        CheckConstraint("sequence > 0", name="ck_ai_run_events_sequence_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_capability_runs.id",
            ondelete="RESTRICT",
            name="fk_ai_run_events_run_id_ai_capability_runs",
        ),
        nullable=False,
    )
    step_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_step_executions.id",
            ondelete="RESTRICT",
            name="fk_ai_run_events_step_exec_id_ai_step_executions",
        ),
        nullable=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    run: Mapped["AICapabilityRun"] = relationship()
    step_execution: Mapped["AIStepExecution | None"] = relationship()


class AIStepOutputSnapshot(Base):
    """AI 步骤候选输出快照表 (P2 Candidate Snapshot)。"""

    __tablename__ = "ai_step_output_snapshots"
    __table_args__ = (
        UniqueConstraint("step_execution_id", name="uq_ai_step_output_snapshots_step_execution_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    step_execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_step_executions.id",
            ondelete="RESTRICT",
            name="fk_ai_step_output_snapshots_step_exec_id",
        ),
        nullable=False,
    )
    output_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    output_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_schema_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    validator_results: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    step_execution: Mapped["AIStepExecution"] = relationship()


class AIHumanGateAction(Base):
    """AI Human Gate 交互决策记录表。"""

    __tablename__ = "ai_human_gate_actions"
    __table_args__ = (
        UniqueConstraint(
            "step_execution_id", "attempt", name="uq_ai_human_gate_actions_step_attempt"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_capability_runs.id", ondelete="RESTRICT", name="fk_ai_human_gate_actions_run_id"
        ),
        nullable=False,
    )
    step_execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_step_executions.id",
            ondelete="RESTRICT",
            name="fk_ai_human_gate_actions_step_exec_id",
        ),
        nullable=False,
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    decision_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    decision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id", ondelete="SET NULL", name="fk_ai_human_gate_actions_submitted_by_users"
        ),
        nullable=True,
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    run: Mapped["AICapabilityRun"] = relationship()
    step_execution: Mapped["AIStepExecution"] = relationship()
    submitter: Mapped["User | None"] = relationship()


class AICapabilityPackage(Base):
    """外部智能体同步的能力包归档快照表。"""

    __tablename__ = "ai_capability_packages"
    __table_args__ = (
        UniqueConstraint(
            "capability_version_id", name="uq_ai_capability_packages_capability_version_id"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    capability_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_capability_versions.id",
            ondelete="CASCADE",
            name="fk_ai_cap_packages_cap_ver_id_ai_cap_vers",
        ),
        nullable=False,
    )
    package_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    validation_report: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    files_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    capability_version: Mapped["AICapabilityVersion"] = relationship()


class AITestDesignRecord(Base):
    """一次可中断、可恢复的四阶段 AI 测试设计生成链。"""

    __tablename__ = "ai_test_design_records"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "task_id",
            "record_no",
            name="uq_ai_test_design_records_project_task_no",
        ),
        UniqueConstraint("run_id", name="uq_ai_test_design_records_run_id"),
        UniqueConstraint(
            "task_id",
            "created_by",
            "idempotency_key",
            name="uq_ai_test_design_records_task_actor_idempotency",
        ),
        CheckConstraint("record_no > 0", name="ck_ai_test_design_records_no_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("test_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("ai_capability_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    record_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    last_opened_stage: Mapped[str] = mapped_column(
        String(50), nullable=False, default="requirement-analysis"
    )
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    run: Mapped["AICapabilityRun"] = relationship()
    task: Mapped["TestTask"] = relationship()
    creator: Mapped["User"] = relationship()


class AIArtifactItem(Base):
    """AI 产物项稳定身份表。"""

    __tablename__ = "ai_artifact_items"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "producer_node_id", "stable_key", name="uq_ai_artifact_items_run_node_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="RESTRICT", name="fk_ai_artifact_items_project_id"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_capability_runs.id", ondelete="RESTRICT", name="fk_ai_artifact_items_run_id"
        ),
        nullable=False,
    )
    producer_node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    stable_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_ai_artifact_items_created_by"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class AIArtifactRevision(Base):
    """AI 产物不可变 Revision 历史正文表。"""

    __tablename__ = "ai_artifact_revisions"
    __table_args__ = (
        UniqueConstraint(
            "artifact_item_id", "revision_no", name="uq_ai_artifact_revisions_item_no"
        ),
        CheckConstraint("revision_no > 0", name="ck_ai_artifact_revisions_no_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="RESTRICT", name="fk_ai_artifact_revisions_project_id"),
        nullable=False,
    )
    artifact_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_artifact_items.id", ondelete="RESTRICT", name="fk_ai_artifact_revisions_item_id"
        ),
        nullable=False,
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_step_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_step_executions.id", ondelete="RESTRICT", name="fk_ai_artifact_revisions_step_exec"
        ),
        nullable=True,
    )
    source_regeneration_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    schema_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    validation_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_ai_artifact_revisions_created_by"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class AIArtifactRevisionParent(Base):
    """Revision DAG 父子关联关系表。"""

    __tablename__ = "ai_artifact_revision_parents"
    __table_args__ = (
        UniqueConstraint(
            "child_revision_id",
            "parent_revision_id",
            name="uq_ai_artifact_rev_parents_child_parent",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    child_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_artifact_revisions.id", ondelete="RESTRICT", name="fk_ai_rev_parents_child"),
        nullable=False,
    )
    parent_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_artifact_revisions.id", ondelete="RESTRICT", name="fk_ai_rev_parents_parent"
        ),
        nullable=False,
    )
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False, default="DERIVED_FROM")
    parent_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AIArtifactSetRevision(Base):
    """完整集合版本表。"""

    __tablename__ = "ai_artifact_set_revisions"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "producer_node_id", "set_revision_no", name="uq_ai_set_revisions_run_node_no"
        ),
        CheckConstraint("set_revision_no > 0", name="ck_ai_set_revisions_no_positive"),
        CheckConstraint("item_count >= 0", name="ck_ai_set_revisions_count_nonnegative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="RESTRICT", name="fk_ai_set_revisions_project_id"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_capability_runs.id", ondelete="RESTRICT", name="fk_ai_set_revisions_run_id"),
        nullable=False,
    )
    producer_node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    set_revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    base_set_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_artifact_set_revisions.id", ondelete="RESTRICT", name="fk_ai_set_revisions_base_id"
        ),
        nullable=True,
    )
    source_step_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_step_executions.id", ondelete="RESTRICT", name="fk_ai_set_revisions_step_exec"
        ),
        nullable=True,
    )
    source_regeneration_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    input_context_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="CANDIDATE")
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN")
    validation_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    decision_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_ai_set_revisions_decision_by"),
        nullable=True,
    )
    decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class AIArtifactSetRevisionMember(Base):
    """集合与 Revision 映射及连续位置表。"""

    __tablename__ = "ai_artifact_set_revision_members"
    __table_args__ = (
        UniqueConstraint("set_revision_id", "artifact_item_id", name="uq_ai_set_members_set_item"),
        UniqueConstraint("set_revision_id", "position", name="uq_ai_set_members_set_position"),
        CheckConstraint("position >= 0", name="ck_ai_set_members_pos_nonnegative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    set_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_artifact_set_revisions.id", ondelete="RESTRICT", name="fk_ai_set_members_set_id"
        ),
        nullable=False,
    )
    artifact_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_artifact_items.id", ondelete="RESTRICT", name="fk_ai_set_members_item_id"),
        nullable=False,
    )
    artifact_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_artifact_revisions.id", ondelete="RESTRICT", name="fk_ai_set_members_rev_id"
        ),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class AICurrentAcceptedRevisionSet(Base):
    """当前已接受黄金集合指针表。"""

    __tablename__ = "ai_current_accepted_revision_sets"
    __table_args__ = (
        UniqueConstraint("run_id", "node_id", name="uq_ai_current_accepted_sets_run_node"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="RESTRICT", name="fk_ai_current_sets_project_id"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_capability_runs.id", ondelete="RESTRICT", name="fk_ai_current_sets_run_id"),
        nullable=False,
    )
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    current_set_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_artifact_set_revisions.id", ondelete="RESTRICT", name="fk_ai_current_sets_set_id"
        ),
        nullable=False,
    )
    acceptance_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_ai_current_sets_accepted_by"),
        nullable=True,
    )
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    freshness_status: Mapped[str] = mapped_column(String(32), nullable=False, default="CURRENT")
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="VALID")
    rerun_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    state_reasons: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    materialized_input_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expected_input_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class AIFieldLock(Base):
    """字段级锁定表。"""

    __tablename__ = "ai_field_locks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="RESTRICT", name="fk_ai_field_locks_project_id"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_capability_runs.id", ondelete="RESTRICT", name="fk_ai_field_locks_run_id"),
        nullable=False,
    )
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_artifact_items.id", ondelete="RESTRICT", name="fk_ai_field_locks_item_id"),
        nullable=False,
    )
    anchor_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_artifact_revisions.id", ondelete="RESTRICT", name="fk_ai_field_locks_anchor_rev"
        ),
        nullable=False,
    )
    json_pointer: Mapped[str] = mapped_column(String(256), nullable=False)
    value_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    last_verified_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_artifact_revisions.id", ondelete="RESTRICT", name="fk_ai_field_locks_last_rev"
        ),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_ai_field_locks_created_by"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    released_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_ai_field_locks_released_by"),
        nullable=True,
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AIFeedback(Base):
    """用户反馈表。"""

    __tablename__ = "ai_feedback"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="RESTRICT", name="fk_ai_feedback_project_id"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_capability_runs.id", ondelete="RESTRICT", name="fk_ai_feedback_run_id"),
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_artifact_items.id", ondelete="RESTRICT", name="fk_ai_feedback_item_id"),
        nullable=True,
    )
    target_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_artifact_revisions.id", ondelete="RESTRICT", name="fk_ai_feedback_rev_id"),
        nullable=True,
    )
    target_step_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_step_executions.id", ondelete="RESTRICT", name="fk_ai_feedback_step_exec"),
        nullable=True,
    )
    json_pointer: Mapped[str | None] = mapped_column(String(256), nullable=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_ai_feedback_created_by"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_ai_feedback_resolved_by"),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AIRegenerationRequest(Base):
    """局部重生成请求快照表。"""

    __tablename__ = "ai_regeneration_requests"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "idempotency_key",
            name="uq_ai_regeneration_requests_run_idempotency",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="RESTRICT", name="fk_ai_regen_reqs_project_id"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_capability_runs.id", ondelete="RESTRICT", name="fk_ai_regen_reqs_run_id"),
        nullable=False,
    )
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    base_set_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_artifact_set_revisions.id", ondelete="RESTRICT", name="fk_ai_regen_reqs_base_set"
        ),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    request_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_ai_regen_reqs_requested_by"),
        nullable=True,
    )
    result_set_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_artifact_set_revisions.id", ondelete="RESTRICT", name="fk_ai_regen_reqs_result_set"
        ),
        nullable=True,
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AIRegenerationRequestItem(Base):
    """局部重生成请求目标 Item 关联表。"""

    __tablename__ = "ai_regeneration_request_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    regeneration_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_regeneration_requests.id", ondelete="CASCADE", name="fk_ai_regen_items_req_id"
        ),
        nullable=False,
    )
    artifact_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_artifact_items.id", ondelete="RESTRICT", name="fk_ai_regen_items_item_id"),
        nullable=False,
    )
    base_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_artifact_revisions.id", ondelete="RESTRICT", name="fk_ai_regen_items_base_rev"
        ),
        nullable=False,
    )
    target_ref: Mapped[str] = mapped_column(String(128), nullable=False)


class AIRegenerationRequestFeedback(Base):
    """局部重生成请求绑定反馈表。"""

    __tablename__ = "ai_regeneration_request_feedback"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    regeneration_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_regeneration_requests.id", ondelete="CASCADE", name="fk_ai_regen_fb_req_id"),
        nullable=False,
    )
    feedback_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_feedback.id", ondelete="RESTRICT", name="fk_ai_regen_fb_fb_id"),
        nullable=False,
    )


class AIContextSnapshot(Base):
    """不可变输入上下文快照表。"""

    __tablename__ = "ai_context_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="RESTRICT", name="fk_ai_context_snapshots_project_id"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_capability_runs.id", ondelete="RESTRICT", name="fk_ai_context_snapshots_run_id"
        ),
        nullable=False,
    )
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    source_step_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_step_executions.id", ondelete="RESTRICT", name="fk_ai_context_snapshots_step_exec"
        ),
        nullable=True,
    )
    source_regeneration_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_regeneration_requests.id",
            ondelete="RESTRICT",
            name="fk_ai_context_snapshots_regen_req",
        ),
        nullable=True,
    )
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint_algorithm: Mapped[str] = mapped_column(
        String(64), nullable=False, default="m09-input-fingerprint-v1"
    )
    upstream_manifest: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class AIDependencyEdge(Base):
    """节点实际消费依赖记录表。"""

    __tablename__ = "ai_dependency_edges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="RESTRICT", name="fk_ai_dep_edges_project_id"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_capability_runs.id", ondelete="RESTRICT", name="fk_ai_dep_edges_run_id"),
        nullable=False,
    )
    upstream_node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    upstream_set_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_artifact_set_revisions.id", ondelete="RESTRICT", name="fk_ai_dep_edges_up_set_id"
        ),
        nullable=False,
    )
    downstream_node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    downstream_context_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_context_snapshots.id", ondelete="RESTRICT", name="fk_ai_dep_edges_down_ctx_id"
        ),
        nullable=False,
    )
    downstream_step_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_step_executions.id", ondelete="RESTRICT", name="fk_ai_dep_edges_down_step_id"
        ),
        nullable=True,
    )
    downstream_output_set_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "ai_artifact_set_revisions.id", ondelete="RESTRICT", name="fk_ai_dep_edges_down_out_set"
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


# ==============================================================================
# M06 测试执行
# ==============================================================================
class ExecutionTaskProfile(Base):
    """执行任务专属信息和高频统计。执行任务复用 M03 test_tasks（task_type=TEST_EXECUTION）。"""

    __tablename__ = "execution_task_profiles"

    execution_task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("test_tasks.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_design_task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("test_tasks.id", ondelete="RESTRICT"), nullable=False
    )
    source_requirement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("requirements.id", ondelete="RESTRICT"), nullable=False
    )
    create_idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    test_environment: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    build_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scope_frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    not_run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocked_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    execution_record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint("total_count >= 0", name="ck_exec_profile_total_nonneg"),
        CheckConstraint("not_run_count >= 0", name="ck_exec_profile_notrun_nonneg"),
        CheckConstraint("passed_count >= 0", name="ck_exec_profile_passed_nonneg"),
        CheckConstraint("failed_count >= 0", name="ck_exec_profile_failed_nonneg"),
        CheckConstraint("blocked_count >= 0", name="ck_exec_profile_blocked_nonneg"),
        CheckConstraint("skipped_count >= 0", name="ck_exec_profile_skipped_nonneg"),
        CheckConstraint("execution_record_count >= 0", name="ck_exec_profile_records_nonneg"),
        # total_count = not_run + passed + failed + blocked + skipped
        CheckConstraint(
            "total_count = not_run_count + passed_count + failed_count"
            " + blocked_count + skipped_count",
            name="ck_exec_profile_total_sum",
        ),
        UniqueConstraint(
            "project_id",
            "source_design_task_id",
            "create_idempotency_key",
            name="uq_exec_profile_project_source_idemp",
        ),
    )


class ExecutionCase(Base):
    """执行任务中的一条固定用例行（不是一次执行）。创建后范围与快照不可变。"""

    __tablename__ = "execution_cases"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    execution_task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("test_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    test_case_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    test_case_revision_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    case_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    case_snapshot_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    current_result: Mapped[str | None] = mapped_column(String(50), nullable=True)
    latest_record_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    latest_actual_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_executed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    latest_executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    execution_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    scope_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("execution_task_id", "test_case_id", name="uq_exec_cases_task_case"),
        CheckConstraint(
            "current_result IS NULL OR current_result IN ('PASSED','FAILED','BLOCKED','SKIPPED')",
            name="ck_exec_cases_result",
        ),
        CheckConstraint("execution_count >= 0", name="ck_exec_cases_count_nonneg"),
        Index("ix_exec_cases_task_current_result", "execution_task_id", "current_result"),
        Index("ix_exec_cases_task_latest_executed_at", "execution_task_id", "latest_executed_at"),
    )


class ExecutionRecord(Base):
    """对某个 ExecutionCase 的一次实际执行记录，追加式、不可覆盖。"""

    __tablename__ = "execution_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    execution_task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("test_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    execution_case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("execution_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    record_no: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[str] = mapped_column(String(50), nullable=False)
    actual_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reason_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    build_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    environment_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    record_source: Mapped[str] = mapped_column(String(50), nullable=False, default="MANUAL")
    correction_of_record_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    correction_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("execution_case_id", "record_no", name="uq_exec_records_case_no"),
        UniqueConstraint(
            "execution_task_id",
            "executed_by",
            "idempotency_key",
            name="uq_exec_records_task_user_idemp",
        ),
        CheckConstraint(
            "result IN ('PASSED','FAILED','BLOCKED','SKIPPED')",
            name="ck_exec_records_result",
        ),
        CheckConstraint(
            "record_source IN ('MANUAL','BATCH_PASS','CORRECTION')",
            name="ck_exec_records_source",
        ),
        CheckConstraint("record_no > 0", name="ck_exec_records_no_pos"),
        Index("ix_exec_records_task_executed_at", "execution_task_id", "executed_at"),
        Index("ix_exec_records_executed_by", "executed_by", "executed_at"),
    )


class ExecutionEvidence(Base):
    """执行证据，必须绑定明确的 execution_record_id。"""

    __tablename__ = "execution_evidences"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    execution_record_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("execution_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    evidence_type: Mapped[str] = mapped_column(String(50), nullable=False)
    object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "evidence_type IN ('IMAGE','TEXT_LOG','ARCHIVE_LOG','EXTERNAL_LINK')",
            name="ck_exec_evidence_type",
        ),
    )


class ExportJob(Base):
    """Excel 导出任务。首版采用同步生成，保留状态与下载凭证以便扩展异步。"""

    __tablename__ = "export_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="PENDING")
    scope_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    file_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','RUNNING','COMPLETED','FAILED','EXPIRED')",
            name="ck_export_jobs_status",
        ),
    )


# =============================================================================
# M09 P5: 评测、优化建议与能力发布闭环实体
# =============================================================================


class AIEvaluationSet(Base):
    """AI 评测集根表 (支持 OFFICIAL 与 PROJECT 作用域)。"""

    __tablename__ = "ai_evaluation_sets"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('OFFICIAL', 'PROJECT')", name="ck_ai_evaluation_sets_scope_type"
        ),
        UniqueConstraint("project_id", "set_key", name="uq_ai_evaluation_sets_proj_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False, default="PROJECT")
    set_key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class AIEvaluationSetRevision(Base):
    """不可变的 AI 评测集版本镜像表。"""

    __tablename__ = "ai_evaluation_set_revisions"
    __table_args__ = (UniqueConstraint("set_id", "revision_no", name="uq_ai_eval_set_rev_no"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    set_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ai_evaluation_sets.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    evaluator_profile_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_frozen: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    case_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class AIEvaluationCase(Base):
    """AI 评测案例根实体。"""

    __tablename__ = "ai_evaluation_cases"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('OFFICIAL', 'PROJECT')", name="ck_ai_evaluation_cases_scope_type"
        ),
        UniqueConstraint("project_id", "case_key", name="uq_ai_eval_cases_proj_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False, default="PROJECT")
    case_key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class AIEvaluationCaseRevision(Base):
    """不可变的评测案例 Revision 表。"""

    __tablename__ = "ai_evaluation_case_revisions"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('MANUAL', 'OFFICIAL_PACKAGE', 'FEEDBACK_RECOMMENDATION', 'ACCEPTED_REVISION_RECOMMENDATION', 'HISTORICAL_FAILURE')",
            name="ck_ai_eval_case_rev_source_type",
        ),
        CheckConstraint(
            "sensitivity IN ('PUBLIC', 'CONFIDENTIAL', 'REDACTED')",
            name="ck_ai_eval_case_rev_sensitivity",
        ),
        UniqueConstraint("case_id", "revision_no", name="uq_ai_eval_case_rev_no"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ai_evaluation_cases.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    inputs_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    human_decision_fixture_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    expected_snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    declarative_assertions_json: Mapped[list[Any]] = mapped_column(
        JSON, nullable=False, default=list
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, default="MANUAL")
    source_ref_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sensitivity: Mapped[str] = mapped_column(String(30), nullable=False, default="CONFIDENTIAL")
    redaction_snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    evaluator_key: Mapped[str] = mapped_column(
        String(100), nullable=False, default="declarative_v1"
    )
    evaluator_version: Mapped[str] = mapped_column(String(50), nullable=False, default="1.0")
    canonical_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class AIEvaluationSetRevisionCase(Base):
    """评测集 Revision 与 Case Revision 关联关系。"""

    __tablename__ = "ai_evaluation_set_revision_cases"
    __table_args__ = (
        UniqueConstraint("set_revision_id", "case_revision_id", name="uq_ai_eval_set_rev_case"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    set_revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("ai_evaluation_set_revisions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    case_revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("ai_evaluation_case_revisions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    weight: Mapped[Numeric] = mapped_column(Numeric(10, 4), nullable=False, default=1.0)


class AIEvaluationCaseRecommendation(Base):
    """评测案例推荐草稿表。"""

    __tablename__ = "ai_evaluation_case_recommendations"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('FEEDBACK', 'ACCEPTED_REVISION', 'HISTORICAL_FAILURE')",
            name="ck_ai_eval_rec_source_type",
        ),
        CheckConstraint(
            "status IN ('PROPOSED', 'ACCEPTED', 'DISMISSED')", name="ck_ai_eval_rec_status"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[str] = mapped_column(String(100), nullable=False)
    suggested_inputs_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    suggested_assertions_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PROPOSED")
    accepted_case_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_evaluation_case_revisions.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class AIEvaluationRun(Base):
    """AI 评测运行主任务表。"""

    __tablename__ = "ai_evaluation_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'PARTIAL', 'FAILED', 'BLOCKED', 'CANCELLED')",
            name="ck_ai_evaluation_runs_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    capability_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ai_capabilities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    capability_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("ai_capability_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    package_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    set_revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("ai_evaluation_set_revisions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    set_revision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluator_profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_profile_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_parameters_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seed_supported: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    total_cases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passed_cases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_cases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_cases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    blocked_cases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_cases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pricing_snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    release_policy_snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class AIEvaluationResult(Base):
    """逐 Case 的评测执行结果表。"""

    __tablename__ = "ai_evaluation_results"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'PASSED', 'FAILED', 'ERROR', 'BLOCKED', 'SKIPPED', 'CANCELLED')",
            name="ck_ai_evaluation_results_status",
        ),
        UniqueConstraint(
            "evaluation_run_id",
            "case_revision_id",
            "repetition_index",
            name="uq_ai_eval_result_case_rep",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    evaluation_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ai_evaluation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("ai_evaluation_case_revisions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    repetition_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    capability_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_capability_runs.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    assertions_passed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    assertions_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[Numeric | None] = mapped_column(Numeric(14, 6), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class AIEvaluationMetricResult(Base):
    """评测声明式指标汇总结果表。"""

    __tablename__ = "ai_evaluation_metric_results"
    __table_args__ = (
        CheckConstraint(
            "direction IN ('HIGHER_IS_BETTER', 'LOWER_IS_BETTER')",
            name="ck_ai_eval_metric_direction",
        ),
        UniqueConstraint("evaluation_run_id", "metric_key", name="uq_ai_eval_metric_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    evaluation_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ai_evaluation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metric_key: Mapped[str] = mapped_column(String(100), nullable=False)
    evaluator_key: Mapped[str] = mapped_column(String(100), nullable=False)
    evaluator_version: Mapped[str] = mapped_column(String(50), nullable=False)
    data_source: Mapped[str] = mapped_column(String(50), nullable=False)
    numerator: Mapped[Numeric | None] = mapped_column(Numeric(16, 6), nullable=True)
    denominator: Mapped[Numeric | None] = mapped_column(Numeric(16, 6), nullable=True)
    value: Mapped[Numeric | None] = mapped_column(Numeric(16, 6), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    direction: Mapped[str] = mapped_column(String(30), nullable=False, default="HIGHER_IS_BETTER")
    sample_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    missing_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    evidence_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    evaluator_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class AIEvaluationComparison(Base):
    """新旧 CapabilityVersion 评测结果比对表。"""

    __tablename__ = "ai_evaluation_comparisons"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'READY', 'NOT_COMPARABLE', 'FAILED')",
            name="ck_ai_eval_comparison_status",
        ),
        UniqueConstraint("baseline_run_id", "candidate_run_id", name="uq_ai_eval_comparison_pair"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    capability_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ai_capabilities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    baseline_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ai_evaluation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ai_evaluation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    baseline_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ai_capability_versions.id", ondelete="RESTRICT"), nullable=False
    )
    candidate_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ai_capability_versions.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    not_comparable_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    summary_diff_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class AIEvaluationComparisonItem(Base):
    """逐 Case 的配对比对细项表。"""

    __tablename__ = "ai_evaluation_comparison_items"
    __table_args__ = (
        UniqueConstraint(
            "comparison_id",
            "case_revision_id",
            "repetition_index",
            name="uq_ai_eval_comp_item_pair",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    comparison_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("ai_evaluation_comparisons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    case_revision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("ai_evaluation_case_revisions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    repetition_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    baseline_result_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_evaluation_results.id", ondelete="SET NULL"), nullable=True
    )
    candidate_result_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_evaluation_results.id", ondelete="SET NULL"), nullable=True
    )
    baseline_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    candidate_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    delta_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class AIQualityObservationSnapshot(Base):
    """生产观察质量聚合快照表。"""

    __tablename__ = "ai_quality_observation_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    capability_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ai_capabilities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    time_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    time_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    normal_run_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    review_coverage: Mapped[Numeric | None] = mapped_column(Numeric(8, 4), nullable=True)
    human_acceptance: Mapped[Numeric | None] = mapped_column(Numeric(8, 4), nullable=True)
    accepted_after_edit: Mapped[Numeric | None] = mapped_column(Numeric(8, 4), nullable=True)
    regeneration_rate: Mapped[Numeric | None] = mapped_column(Numeric(8, 4), nullable=True)
    failure_rate: Mapped[Numeric | None] = mapped_column(Numeric(8, 4), nullable=True)
    duration_p50_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_p95_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_cost: Mapped[Numeric | None] = mapped_column(Numeric(14, 6), nullable=True)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class AIOptimizationSuggestion(Base):
    """优化建议实体表 (基于真实 Evidence 结构化生成)。"""

    __tablename__ = "ai_optimization_suggestions"
    __table_args__ = (
        CheckConstraint(
            "suggestion_type IN ('PROMPT', 'SCHEMA', 'WORKFLOW', 'VALIDATOR', 'MODEL_POLICY', 'EVALUATION_CASE', 'DOCUMENTATION')",
            name="ck_ai_opt_suggestion_type",
        ),
        CheckConstraint(
            "status IN ('OPEN', 'PACKAGED', 'DISMISSED', 'RESOLVED')",
            name="ck_ai_opt_suggestion_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    capability_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ai_capabilities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    suggestion_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    time_window_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    impacted_cases_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    suggested_action_area: Mapped[str] = mapped_column(String(100), nullable=False)
    risk_assessment: Mapped[str] = mapped_column(Text, nullable=False)
    uncertainty_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="OPEN")
    resolved_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_capability_versions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class AIWorkspacePackage(Base):
    """导出的不可变 Workspace Package 凭证包实体表。"""

    __tablename__ = "ai_workspace_packages"
    __table_args__ = (
        CheckConstraint(
            "package_type IN ('FEEDBACK', 'EVALUATION', 'OPTIMIZATION')",
            name="ck_ai_ws_package_type",
        ),
        CheckConstraint(
            "status IN ('READY', 'REVOKED', 'EXPIRED', 'SUPERSEDED')",
            name="ck_ai_ws_package_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    capability_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ai_capabilities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    package_type: Mapped[str] = mapped_column(String(30), nullable=False)
    package_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    schema_version: Mapped[str] = mapped_column(String(30), nullable=False, default="1.0")
    base_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_capability_versions.id", ondelete="SET NULL"), nullable=True
    )
    candidate_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_capability_versions.id", ondelete="SET NULL"), nullable=True
    )
    base_package_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evaluation_set_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_evaluation_set_revisions.id", ondelete="SET NULL"), nullable=True
    )
    suggestion_ids_json: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    evidence_manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="READY")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class AICapabilityReleaseRequest(Base):
    """能力发布评审与决策请求实体表。"""

    __tablename__ = "ai_capability_release_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'VALIDATING', 'IN_REVIEW', 'APPROVED', 'REJECTED', 'CANCELLED', 'RELEASED')",
            name="ck_ai_rel_req_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    capability_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ai_capabilities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ai_capability_versions.id", ondelete="RESTRICT"), nullable=False
    )
    base_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_capability_versions.id", ondelete="RESTRICT"), nullable=True
    )
    package_fingerprints_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    evaluation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_evaluation_runs.id", ondelete="SET NULL"), nullable=True
    )
    comparison_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_evaluation_comparisons.id", ondelete="SET NULL"), nullable=True
    )
    config_diff_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    blocking_checks_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    advisories_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    policy_provider_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    rollback_target_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_capability_versions.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT")
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class AICapabilityDeployment(Base):
    """单一 Capability 的独立 Deployment 部署实体表。"""

    __tablename__ = "ai_capability_deployments"
    __table_args__ = (
        CheckConstraint(
            "canary_basis_points >= 0 AND canary_basis_points <= 10000",
            name="ck_ai_deploy_canary_bp",
        ),
        CheckConstraint("status IN ('ACTIVE', 'DISABLED')", name="ck_ai_deploy_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    capability_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("ai_capabilities.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    stable_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ai_capability_versions.id", ondelete="RESTRICT"), nullable=False
    )
    canary_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_capability_versions.id", ondelete="RESTRICT"), nullable=True
    )
    canary_basis_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    routing_salt: Mapped[str] = mapped_column(String(64), nullable=False)
    deployment_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ACTIVE")
    active_release_request_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_capability_release_requests.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class AICapabilityReleaseAction(Base):
    """不可变发布/灰度/回滚历史操作审计表。"""

    __tablename__ = "ai_capability_release_actions"
    __table_args__ = (
        CheckConstraint(
            "action_type IN ('FULL_RELEASE', 'START_CANARY', 'ADJUST_CANARY', 'PROMOTE_CANARY', 'ROLLBACK')",
            name="ck_ai_rel_action_type",
        ),
        CheckConstraint(
            "canary_basis_points >= 0 AND canary_basis_points <= 10000",
            name="ck_ai_rel_action_canary_bp",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    capability_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ai_capabilities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    deployment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("ai_capability_deployments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    release_request_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_capability_release_requests.id", ondelete="SET NULL"), nullable=True
    )
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    stable_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ai_capability_versions.id", ondelete="RESTRICT"), nullable=False
    )
    canary_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_capability_versions.id", ondelete="RESTRICT"), nullable=True
    )
    canary_basis_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deployment_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class ExternalAgentToken(Base):
    """External Agent 用户委托 Access Token 表 (前缀 tw_ext_)。"""

    __tablename__ = "external_agent_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    token_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class CandidateSubmission(Base):
    """外接 Agent 提交候选版本与测试点/用例快照表"""

    __tablename__ = "candidate_submissions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    capability_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ai_capabilities.id", ondelete="SET NULL"), nullable=True, index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("test_tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    submitted_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="SUBMITTED", nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    published_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    auto_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class IdempotencyKey(Base):
    """外接 Agent 网关全局幂等记录表"""

    __tablename__ = "idempotency_keys"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "project_id", "endpoint", "idempotency_key", name="uq_idempotency_key_proj_ep_key"
        ),
    )


class UserRecentVisit(Base):
    """M01 个人工作台用户最近访问持久化表"""

    __tablename__ = "user_recent_visits"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(100), nullable=False)
    visited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "project_id",
            "resource_type",
            "resource_id",
            name="uq_user_recent_visits_unique",
        ),
        Index(
            "ix_user_recent_visits_user_project_visited",
            "user_id",
            "project_id",
            "visited_at",
        ),
    )
