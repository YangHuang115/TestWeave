"""REQ-10016 add project AI Skill registry tables.

Revision ID: c16f10016002
Revises: b27c10017001
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c16f10016002"
down_revision: str | None = "b27c10017001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_skills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("maintainer_id", sa.Uuid(), nullable=True),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("current_published_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'ARCHIVED')",
            name="ck_ai_skills_status_values",
        ),
        sa.ForeignKeyConstraint(
            ["maintainer_id"],
            ["users.id"],
            name="fk_ai_skills_maintainer_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_ai_skills_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "code", name="uq_ai_skills_project_code"),
    )
    op.create_index(op.f("ix_ai_skills_project_id"), "ai_skills", ["project_id"], unique=False)

    op.create_table(
        "ai_skill_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("package_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("manifest_snapshot", sa.JSON(), nullable=False),
        sa.Column("input_schema", sa.JSON(), nullable=False),
        sa.Column("output_schema", sa.JSON(), nullable=False),
        sa.Column("model_policy", sa.String(length=50), nullable=False),
        sa.Column("allowed_tools", sa.JSON(), nullable=False),
        sa.Column("required_permissions", sa.JSON(), nullable=False),
        sa.Column("side_effect_level", sa.String(length=10), nullable=False),
        sa.Column("created_source", sa.String(length=50), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('SYNCED_DRAFT', 'PUBLISHED', 'REJECTED', 'DEPRECATED')",
            name="ck_ai_skill_versions_status_values",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_ai_skill_versions_created_by_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["ai_skills.id"],
            name="fk_ai_skill_versions_skill_id_ai_skills",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "skill_id",
            "version",
            name="uq_ai_skill_versions_skill_version",
        ),
    )
    op.create_index(
        op.f("ix_ai_skill_versions_skill_id"),
        "ai_skill_versions",
        ["skill_id"],
        unique=False,
    )

    op.create_table(
        "ai_skill_packages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("skill_version_id", sa.Uuid(), nullable=False),
        sa.Column("package_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("validation_report", sa.JSON(), nullable=False),
        sa.Column("files_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["skill_version_id"],
            ["ai_skill_versions.id"],
            name="fk_ai_skill_packages_skill_version_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "skill_version_id",
            name="uq_ai_skill_packages_skill_version_id",
        ),
    )
    op.create_table(
        "ai_capability_skill_bindings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("capability_version_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.String(length=100), nullable=False),
        sa.Column("skill_version_id", sa.Uuid(), nullable=False),
        sa.Column("package_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["capability_version_id"],
            ["ai_capability_versions.id"],
            name="fk_ai_capability_skill_bindings_capability_version_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_version_id"],
            ["ai_skill_versions.id"],
            name="fk_ai_capability_skill_bindings_skill_version_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "capability_version_id",
            "node_id",
            name="uq_ai_capability_skill_bindings_capability_node",
        ),
    )
    op.create_index(
        op.f("ix_ai_capability_skill_bindings_capability_version_id"),
        "ai_capability_skill_bindings",
        ["capability_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_capability_skill_bindings_skill_version_id"),
        "ai_capability_skill_bindings",
        ["skill_version_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_ai_skills_current_published_version_id",
        "ai_skills",
        "ai_skill_versions",
        ["current_published_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_ai_skills_current_published_version_id",
        "ai_skills",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_ai_capability_skill_bindings_skill_version_id"),
        table_name="ai_capability_skill_bindings",
    )
    op.drop_index(
        op.f("ix_ai_capability_skill_bindings_capability_version_id"),
        table_name="ai_capability_skill_bindings",
    )
    op.drop_table("ai_capability_skill_bindings")
    op.drop_table("ai_skill_packages")
    op.drop_index(op.f("ix_ai_skill_versions_skill_id"), table_name="ai_skill_versions")
    op.drop_table("ai_skill_versions")
    op.drop_index(op.f("ix_ai_skills_project_id"), table_name="ai_skills")
    op.drop_table("ai_skills")
