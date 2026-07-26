import copy
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    AICapability,
    AICapabilityPackage,
    AICapabilityVersion,
    AISkill,
    AISkillVersion,
)
from testweave.modules.ai_capability.runtime.snapshots import calculate_json_hash
from testweave.modules.ai_skill.service import SkillRegistryService
from testweave.modules.ai_test_design.constants import (
    BUILTIN_CAPABILITY_CODE,
    BUILTIN_INPUT_SCHEMA,
    BUILTIN_WORKFLOW,
)

WORKBENCH_SKILL_NODES = {
    "requirement_analysis": "requirement-analysis",
    "test_points": "test-point-generation",
    "test_cases": "test-case-generation",
    "case_review": "test-case-review",
}


class BuiltinAiTestDesignCapabilityService:
    """从项目已发布 Skill 版本组装并固定工作台能力版本。"""

    @classmethod
    def ensure_published(
        cls,
        db: Session,
        actor_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> AICapability:
        skill_versions = cls._resolve_published_skill_versions(db, project_id)
        workflow = copy.deepcopy(BUILTIN_WORKFLOW)
        binding_fingerprints: dict[str, dict[str, str]] = {}

        for node_id, skill_code in WORKBENCH_SKILL_NODES.items():
            skill, skill_version = skill_versions[skill_code]
            node = workflow["nodes"][node_id]
            node["skill_version_id"] = str(skill_version.id)
            node["input_schema"] = skill_version.input_schema
            node["output_schema"] = skill_version.output_schema
            node["model_policy"] = skill_version.model_policy
            binding_fingerprints[node_id] = {
                "skillId": str(skill.id),
                "skillVersionId": str(skill_version.id),
                "packageFingerprint": skill_version.package_fingerprint,
            }

        package_files = {
            "workflow.json": workflow,
            "schemas/input.schema.json": BUILTIN_INPUT_SCHEMA,
        }
        package_fingerprint = calculate_json_hash(
            {
                "files": package_files,
                "skillBindings": binding_fingerprints,
            }
        )
        capability_version_name = f"skillset-{package_fingerprint[:16]}"
        namespace = f"project/{project_id}"

        capability = db.scalar(
            select(AICapability).where(
                AICapability.namespace == namespace,
                AICapability.code == BUILTIN_CAPABILITY_CODE,
            )
        )
        if capability is None:
            capability = AICapability(
                namespace=namespace,
                code=BUILTIN_CAPABILITY_CODE,
                name="AI 测试设计工作台",
                category="TEST_DESIGN_WORKBENCH",
                scope="PROJECT",
                project_id=project_id,
                status="ACTIVE",
            )
            db.add(capability)
            db.flush()

        version = db.scalar(
            select(AICapabilityVersion).where(
                AICapabilityVersion.capability_id == capability.id,
                AICapabilityVersion.version == capability_version_name,
            )
        )
        if version is None:
            version = AICapabilityVersion(
                capability_id=capability.id,
                version=capability_version_name,
                status="PUBLISHED",
                package_fingerprint=package_fingerprint,
                compatibility_level="PLATFORM_NATIVE",
                workflow_snapshot=workflow,
                input_schema=BUILTIN_INPUT_SCHEMA,
                output_schema=None,
                created_source="SKILL_REGISTRY",
                created_by=actor_id,
                published_at=datetime.now(UTC),
            )
            db.add(version)
            db.flush()
            db.add(
                AICapabilityPackage(
                    capability_version_id=version.id,
                    package_fingerprint=package_fingerprint,
                    validation_report={
                        "valid": True,
                        "source": "SKILL_REGISTRY",
                        "skillBindings": binding_fingerprints,
                    },
                    files_snapshot=package_files,
                )
            )
            db.flush()
        else:
            package = db.scalar(
                select(AICapabilityPackage).where(
                    AICapabilityPackage.capability_version_id == version.id
                )
            )
            if (
                package is None
                or package.package_fingerprint != package_fingerprint
                or version.package_fingerprint != package_fingerprint
            ):
                raise AppError(
                    code="AI_TEST_DESIGN_CAPABILITY_INTEGRITY_ERROR",
                    message="AI 测试设计能力版本快照完整性校验失败",
                    status_code=409,
                )

        SkillRegistryService.bind_capability_version(
            db=db,
            project_id=project_id,
            capability_version_id=version.id,
            node_skill_versions={
                node_id: skill_versions[skill_code][1].id
                for node_id, skill_code in WORKBENCH_SKILL_NODES.items()
            },
        )

        previous_version_id = capability.current_published_version_id
        if previous_version_id and previous_version_id != version.id:
            previous_version = db.get(AICapabilityVersion, previous_version_id)
            if previous_version is not None and previous_version.status == "PUBLISHED":
                previous_version.status = "DEPRECATED"
        version.status = "PUBLISHED"
        capability.current_published_version_id = version.id
        db.commit()
        return capability

    @staticmethod
    def _resolve_published_skill_versions(
        db: Session,
        project_id: uuid.UUID,
    ) -> dict[str, tuple[AISkill, AISkillVersion]]:
        resolved: dict[str, tuple[AISkill, AISkillVersion]] = {}
        missing: list[str] = []

        for skill_code in WORKBENCH_SKILL_NODES.values():
            skill = db.scalar(
                select(AISkill).where(
                    AISkill.project_id == project_id,
                    AISkill.code == skill_code,
                    AISkill.status == "ACTIVE",
                )
            )
            skill_version = (
                db.get(AISkillVersion, skill.current_published_version_id)
                if skill is not None and skill.current_published_version_id
                else None
            )
            if (
                skill is None
                or skill_version is None
                or skill_version.skill_id != skill.id
                or skill_version.status != "PUBLISHED"
            ):
                missing.append(skill_code)
                continue
            resolved[skill_code] = (skill, skill_version)

        if missing:
            raise AppError(
                code="AI_TEST_DESIGN_SKILLS_NOT_READY",
                message="AI 测试设计工作台所需 Skill 尚未全部注册并发布",
                status_code=409,
                details={"missingSkillCodes": sorted(missing)},
            )
        return resolved
