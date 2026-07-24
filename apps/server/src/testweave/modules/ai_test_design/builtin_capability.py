import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.db.models import AICapability, AICapabilityPackage, AICapabilityVersion
from testweave.modules.ai_capability.runtime.snapshots import calculate_json_hash
from testweave.modules.ai_test_design.constants import (
    BUILTIN_CAPABILITY_CODE,
    BUILTIN_CAPABILITY_NAMESPACE,
    BUILTIN_CAPABILITY_VERSION,
    BUILTIN_INPUT_SCHEMA,
    BUILTIN_PACKAGE_FILES,
    BUILTIN_WORKFLOW,
)


class BuiltinAiTestDesignCapabilityService:
    """确保官方工作台能力以不可变已发布快照存在。"""

    @classmethod
    def ensure_published(
        cls,
        db: Session,
        actor_id: uuid.UUID,
    ) -> AICapability:
        capability = db.scalar(
            select(AICapability).where(
                AICapability.namespace == BUILTIN_CAPABILITY_NAMESPACE,
                AICapability.code == BUILTIN_CAPABILITY_CODE,
            )
        )
        if capability is None:
            capability = AICapability(
                namespace=BUILTIN_CAPABILITY_NAMESPACE,
                code=BUILTIN_CAPABILITY_CODE,
                name="AI 测试设计工作台",
                category="TEST_DESIGN_WORKBENCH",
                scope="OFFICIAL",
                project_id=None,
                status="ACTIVE",
            )
            db.add(capability)
            db.flush()

        version = db.scalar(
            select(AICapabilityVersion).where(
                AICapabilityVersion.capability_id == capability.id,
                AICapabilityVersion.version == BUILTIN_CAPABILITY_VERSION,
            )
        )
        package_fingerprint = calculate_json_hash(BUILTIN_PACKAGE_FILES)
        if version is None:
            version = AICapabilityVersion(
                capability_id=capability.id,
                version=BUILTIN_CAPABILITY_VERSION,
                status="PUBLISHED",
                package_fingerprint=package_fingerprint,
                compatibility_level="PLATFORM_NATIVE",
                workflow_snapshot=BUILTIN_WORKFLOW,
                input_schema=BUILTIN_INPUT_SCHEMA,
                output_schema=None,
                created_source="BUILTIN",
                created_by=actor_id,
                published_at=datetime.now(UTC),
            )
            db.add(version)
            db.flush()

        package = db.scalar(
            select(AICapabilityPackage).where(
                AICapabilityPackage.capability_version_id == version.id
            )
        )
        if package is None:
            package = AICapabilityPackage(
                capability_version_id=version.id,
                package_fingerprint=package_fingerprint,
                validation_report={"valid": True, "source": "BUILTIN"},
                files_snapshot=BUILTIN_PACKAGE_FILES,
            )
            db.add(package)
            db.flush()

        if capability.current_published_version_id != version.id:
            capability.current_published_version_id = version.id
            db.flush()
        return capability
