import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from jsonschema import Draft7Validator
from jsonschema.exceptions import SchemaError
from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    AICapability,
    AICapabilitySkillBinding,
    AICapabilityVersion,
    AISkill,
    AISkillPackage,
    AISkillVersion,
)
from testweave.modules.ai_capability.external_agent.token_service import (
    ExternalAgentTokenService,
)
from testweave.modules.ai_capability.schemas import FileMapping
from testweave.modules.ai_capability.service import safe_yaml_load
from testweave.modules.audit.service import AuditService

_SKILL_CODE_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
_REQUIRED_MANIFEST_FIELDS = {
    "id",
    "version",
    "name",
    "description",
    "prompt",
    "input_schema",
    "output_schema",
    "model_policy",
    "allowed_tools",
    "required_permissions",
    "side_effect_level",
}
_MODEL_POLICIES = {"quality_first", "balanced", "cost_first"}
_SIDE_EFFECT_LEVELS = {"L0", "L1"}
_REGISTERED_TOOLS: set[str] = set()
_ALLOWED_REQUIRED_PERMISSIONS = {
    "project.read",
    "requirement.read",
    "test_task.read",
}
_MAX_FILES = 128
_MAX_FILE_SIZE = 1024 * 1024
_MAX_PACKAGE_SIZE = 5 * 1024 * 1024
_MAX_PATH_LENGTH = 240
_MAX_PATH_DEPTH = 12
_ALLOWED_ROOT_FILES = {
    "manifest.yaml",
    "SKILL.md",
    "prompt.md",
    "input.schema.json",
    "output.schema.json",
    "CHANGELOG.md",
}
_ALLOWED_SUPPORT_SUFFIXES = {".json", ".md", ".yaml", ".yml"}


class SkillRegistryService:
    """项目级 Skill 注册表服务。"""

    @classmethod
    def validate_package(cls, files: list[FileMapping]) -> dict[str, Any]:
        issues: list[str] = []
        file_map: dict[str, str] = {}
        total_size = 0

        if not files:
            issues.append("Skill 包文件不能为空")
        if len(files) > _MAX_FILES:
            issues.append(f"Skill 包文件数不能超过 {_MAX_FILES}")

        for file in files:
            raw_path = file.path
            path = raw_path.strip()
            content_size = len(file.content.encode("utf-8"))
            total_size += content_size

            if raw_path != path or not cls._is_safe_path(path):
                issues.append(f"文件路径不安全或不规范: {file.path}")
                continue
            if not cls._is_allowed_package_path(path):
                issues.append(f"Skill 包文件路径或类型不受支持: {path}")
                continue
            if path in file_map:
                issues.append(f"文件路径重复: {path}")
                continue
            if len(path) > _MAX_PATH_LENGTH:
                issues.append(f"文件路径长度超过 {_MAX_PATH_LENGTH}: {path}")
            if len(PurePosixPath(path).parts) - 1 > _MAX_PATH_DEPTH:
                issues.append(f"文件路径目录深度超过 {_MAX_PATH_DEPTH}: {path}")
            if content_size > _MAX_FILE_SIZE:
                issues.append(f"单文件超过 1 MiB: {path}")
            file_map[path] = file.content

        if total_size > _MAX_PACKAGE_SIZE:
            issues.append("Skill 包总大小超过 5 MiB")

        required_files = {"manifest.yaml", "SKILL.md"}
        missing_files = sorted(required_files.difference(file_map))
        if missing_files:
            issues.append(f"缺少必需文件: {', '.join(missing_files)}")

        manifest: dict[str, Any] | None = None
        skill_info: dict[str, Any] | None = None
        input_schema: dict[str, Any] | None = None
        output_schema: dict[str, Any] | None = None

        if "manifest.yaml" in file_map:
            try:
                loaded = safe_yaml_load(file_map["manifest.yaml"])
                if not isinstance(loaded, dict):
                    raise ValueError("根节点必须是对象")
                manifest = loaded
            except Exception as exc:
                issues.append(f"manifest.yaml 解析失败: {exc!s}")

        if manifest is not None:
            unknown_root = set(manifest).difference({"protocol_version", "skill"})
            if unknown_root:
                issues.append(f"manifest.yaml 包含未知根字段: {', '.join(sorted(unknown_root))}")
            if manifest.get("protocol_version") != "1.0":
                issues.append("protocol_version 必须为 1.0")
            candidate = manifest.get("skill")
            if not isinstance(candidate, dict):
                issues.append("manifest.yaml 缺少 skill 对象")
            else:
                skill_info = candidate
                missing_fields = _REQUIRED_MANIFEST_FIELDS.difference(candidate)
                unknown_fields = set(candidate).difference(_REQUIRED_MANIFEST_FIELDS)
                if missing_fields:
                    issues.append(f"skill 清单缺少字段: {', '.join(sorted(missing_fields))}")
                if unknown_fields:
                    issues.append(f"skill 清单包含未知字段: {', '.join(sorted(unknown_fields))}")

        if skill_info is not None:
            cls._validate_skill_manifest(skill_info, file_map, issues)
            input_schema = cls._load_schema(
                "input Schema",
                skill_info.get("input_schema"),
                file_map,
                issues,
            )
            output_schema = cls._load_schema(
                "output Schema",
                skill_info.get("output_schema"),
                file_map,
                issues,
            )
            cls._validate_skill_md(
                file_map.get("SKILL.md"),
                expected_name=skill_info.get("id"),
                issues=issues,
            )

        package_fingerprint = cls._fingerprint(file_map) if file_map else None
        return {
            "valid": not issues,
            "issues": issues,
            "packageFingerprint": package_fingerprint,
            "manifest": manifest,
            "skill": skill_info,
            "inputSchema": input_schema,
            "outputSchema": output_schema,
            "filesSnapshot": file_map,
        }

    @classmethod
    def sync_draft(
        cls,
        *,
        db: Session,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        effective_scopes: list[str],
        files: list[FileMapping],
        request_id: str = "external-skill-sync",
    ) -> dict[str, Any]:
        ExternalAgentTokenService.verify_scope(effective_scopes, "skill:sync")
        report = cls.validate_package(files)
        if not report["valid"]:
            raise AppError(
                code="SKILL_PACKAGE_INVALID",
                message="Skill 包校验失败",
                status_code=400,
                details={"issues": report["issues"]},
            )

        skill_info = report["skill"]
        assert skill_info is not None
        fingerprint = report["packageFingerprint"]
        assert isinstance(fingerprint, str)

        skill = db.scalar(
            select(AISkill).where(
                AISkill.project_id == project_id,
                AISkill.code == skill_info["id"],
            )
        )
        now = datetime.now(UTC)
        if skill is None:
            skill = AISkill(
                id=uuid.uuid4(),
                project_id=project_id,
                maintainer_id=user_id,
                code=skill_info["id"],
                name=skill_info["name"].strip(),
                description=skill_info["description"].strip(),
                status="ACTIVE",
                created_at=now,
                updated_at=now,
            )
            db.add(skill)
            db.flush()
        else:
            if skill.maintainer_id is None:
                skill.maintainer_id = user_id
            skill.name = skill_info["name"].strip()
            skill.description = skill_info["description"].strip()
            skill.updated_at = now

        existing_version = db.scalar(
            select(AISkillVersion).where(
                AISkillVersion.skill_id == skill.id,
                AISkillVersion.version == skill_info["version"],
            )
        )
        if existing_version is not None:
            if existing_version.package_fingerprint != fingerprint:
                db.rollback()
                raise AppError(
                    code="SKILL_VERSION_CONFLICT",
                    message=(
                        f"Skill {skill.code} 的版本 {existing_version.version} 已存在且内容不同，"
                        "请提升版本号后再同步"
                    ),
                    status_code=409,
                )
            db.commit()
            return cls._sync_response("UNCHANGED", skill, existing_version)

        version = AISkillVersion(
            id=uuid.uuid4(),
            skill_id=skill.id,
            version=skill_info["version"],
            status="SYNCED_DRAFT",
            package_fingerprint=fingerprint,
            manifest_snapshot=report["manifest"],
            input_schema=report["inputSchema"],
            output_schema=report["outputSchema"],
            model_policy=skill_info["model_policy"],
            allowed_tools=skill_info["allowed_tools"],
            required_permissions=skill_info["required_permissions"],
            side_effect_level=skill_info["side_effect_level"],
            created_source="EXTERNAL_SYNC",
            created_by=user_id,
            created_at=now,
        )
        db.add(version)
        db.flush()
        db.add(
            AISkillPackage(
                id=uuid.uuid4(),
                skill_version_id=version.id,
                package_fingerprint=fingerprint,
                validation_report={
                    "valid": True,
                    "issues": [],
                    "packageFingerprint": fingerprint,
                },
                files_snapshot=report["filesSnapshot"],
                created_at=now,
            )
        )
        AuditService.log_event(
            db,
            project_id=project_id,
            actor_id=user_id,
            action="ai_skill_version_synced",
            object_type="ai_skill_version",
            object_id=str(version.id),
            summary=f"同步 Skill {skill.code} 版本 {version.version} 草稿",
            request_id=request_id,
        )
        db.commit()
        return cls._sync_response("SYNCED", skill, version)

    @classmethod
    def publish_version(
        cls,
        *,
        db: Session,
        project_id: uuid.UUID,
        skill_id: uuid.UUID,
        version_id: uuid.UUID,
        actor_id: uuid.UUID,
        request_id: str,
    ) -> dict[str, Any]:
        skill = db.scalar(
            select(AISkill).where(
                AISkill.id == skill_id,
                AISkill.project_id == project_id,
            )
        )
        if skill is None:
            raise AppError(
                code="SKILL_NOT_FOUND",
                message="Skill 不存在或不属于当前项目",
                status_code=404,
            )
        version = db.scalar(
            select(AISkillVersion).where(
                AISkillVersion.id == version_id,
                AISkillVersion.skill_id == skill.id,
            )
        )
        if version is None:
            raise AppError(
                code="SKILL_VERSION_NOT_FOUND",
                message="Skill 版本不存在",
                status_code=404,
            )
        if version.status not in {"SYNCED_DRAFT", "PUBLISHED"}:
            raise AppError(
                code="SKILL_VERSION_NOT_PUBLISHABLE",
                message=f"当前 Skill 版本状态 {version.status} 不允许发布",
                status_code=409,
            )

        now = datetime.now(UTC)
        previous_version_id = skill.current_published_version_id
        if previous_version_id and previous_version_id != version.id:
            previous = db.get(AISkillVersion, previous_version_id)
            if previous is not None and previous.status == "PUBLISHED":
                previous.status = "DEPRECATED"

        version.status = "PUBLISHED"
        version.published_at = version.published_at or now
        skill.current_published_version_id = version.id
        skill.updated_at = now
        AuditService.log_event(
            db,
            project_id=project_id,
            actor_id=actor_id,
            action="ai_skill_version_published",
            object_type="ai_skill_version",
            object_id=str(version.id),
            summary=f"发布 Skill {skill.code} 版本 {version.version}",
            request_id=request_id,
        )
        db.commit()
        return {
            "skillId": str(skill.id),
            "versionId": str(version.id),
            "version": version.version,
            "status": version.status,
        }

    @classmethod
    def bind_capability_version(
        cls,
        *,
        db: Session,
        project_id: uuid.UUID,
        capability_version_id: uuid.UUID,
        node_skill_versions: dict[str, uuid.UUID],
    ) -> list[AICapabilitySkillBinding]:
        capability_version = db.scalar(
            select(AICapabilityVersion)
            .join(AICapability, AICapability.id == AICapabilityVersion.capability_id)
            .where(
                AICapabilityVersion.id == capability_version_id,
                AICapability.project_id == project_id,
                AICapability.scope == "PROJECT",
            )
        )
        if capability_version is None:
            raise AppError(
                code="CAPABILITY_VERSION_NOT_FOUND",
                message="项目能力版本不存在",
                status_code=404,
            )

        nodes = (capability_version.workflow_snapshot or {}).get("nodes", {})
        if not isinstance(nodes, dict):
            raise AppError(
                code="CAPABILITY_WORKFLOW_INVALID",
                message="能力版本 Workflow 节点结构非法",
                status_code=400,
            )

        bindings: list[AICapabilitySkillBinding] = []
        for node_id, skill_version_id in node_skill_versions.items():
            node = nodes.get(node_id)
            if not isinstance(node, dict) or str(node.get("type", "")).upper() != "SKILL":
                raise AppError(
                    code="CAPABILITY_SKILL_NODE_INVALID",
                    message=f"Workflow 节点 {node_id} 不是有效的 SKILL 节点",
                    status_code=400,
                )
            declared_version_id = node.get("skill_version_id")
            if declared_version_id and str(declared_version_id) != str(skill_version_id):
                raise AppError(
                    code="CAPABILITY_SKILL_BINDING_CONFLICT",
                    message=f"节点 {node_id} 声明的 Skill 版本与绑定请求不一致",
                    status_code=409,
                )

            skill_version = db.scalar(
                select(AISkillVersion)
                .join(AISkill, AISkill.id == AISkillVersion.skill_id)
                .where(
                    AISkillVersion.id == skill_version_id,
                    AISkillVersion.status == "PUBLISHED",
                    AISkill.project_id == project_id,
                    AISkill.status == "ACTIVE",
                )
            )
            if skill_version is None:
                raise AppError(
                    code="SKILL_VERSION_NOT_PUBLISHED",
                    message=f"节点 {node_id} 绑定的 Skill 版本未发布或不属于当前项目",
                    status_code=409,
                )
            skill = db.get(AISkill, skill_version.skill_id)
            if skill is None or skill.code != node.get("skill"):
                raise AppError(
                    code="CAPABILITY_SKILL_BINDING_CONFLICT",
                    message=f"节点 {node_id} 的 Skill code 与版本不匹配",
                    status_code=409,
                )

            existing = db.scalar(
                select(AICapabilitySkillBinding).where(
                    AICapabilitySkillBinding.capability_version_id == capability_version.id,
                    AICapabilitySkillBinding.node_id == node_id,
                )
            )
            if existing is not None:
                if existing.skill_version_id != skill_version.id:
                    raise AppError(
                        code="CAPABILITY_SKILL_BINDING_CONFLICT",
                        message=f"节点 {node_id} 已绑定其他 Skill 版本",
                        status_code=409,
                    )
                bindings.append(existing)
                continue

            binding = AICapabilitySkillBinding(
                id=uuid.uuid4(),
                capability_version_id=capability_version.id,
                node_id=node_id,
                skill_version_id=skill_version.id,
                package_fingerprint=skill_version.package_fingerprint,
                created_at=datetime.now(UTC),
            )
            db.add(binding)
            bindings.append(binding)

        db.flush()
        return bindings

    @classmethod
    def resolve_runtime_materials(
        cls,
        *,
        db: Session,
        project_id: uuid.UUID,
        capability_version_id: uuid.UUID,
        workflow_snapshot: dict[str, Any],
        capability_files: dict[str, Any],
    ) -> dict[str, Any]:
        capability_version = db.scalar(
            select(AICapabilityVersion)
            .join(AICapability, AICapability.id == AICapabilityVersion.capability_id)
            .where(
                AICapabilityVersion.id == capability_version_id,
                AICapability.project_id == project_id,
            )
        )
        if capability_version is None:
            raise AppError(
                code="RUN_SKILL_BINDING_INVALID",
                message="运行能力版本不属于当前项目",
                status_code=400,
            )

        bindings = list(
            db.scalars(
                select(AICapabilitySkillBinding).where(
                    AICapabilitySkillBinding.capability_version_id == capability_version_id
                )
            ).all()
        )
        binding_by_node = {binding.node_id: binding for binding in bindings}
        nodes = workflow_snapshot.get("nodes", {})
        if not isinstance(nodes, dict):
            raise AppError(
                code="RUN_SKILL_BINDING_INVALID",
                message="Workflow 节点结构非法",
                status_code=400,
            )

        package_files = dict(capability_files)
        binding_snapshot: dict[str, dict[str, str]] = {}
        visited_bindings: set[str] = set()

        for node_id, node in nodes.items():
            if not isinstance(node, dict) or str(node.get("type", "")).upper() != "SKILL":
                continue
            declared_version_id = node.get("skill_version_id")
            binding = binding_by_node.get(node_id)
            if declared_version_id is None and binding is None:
                continue
            if binding is None or (
                declared_version_id is not None
                and str(binding.skill_version_id) != str(declared_version_id)
            ):
                raise AppError(
                    code="RUN_SKILL_BINDING_INVALID",
                    message=f"节点 {node_id} 缺少匹配的 Skill 版本绑定",
                    status_code=400,
                )

            skill_version = db.get(AISkillVersion, binding.skill_version_id)
            if skill_version is None:
                raise AppError(
                    code="RUN_SKILL_BINDING_INVALID",
                    message=f"节点 {node_id} 的 Skill 版本不存在",
                    status_code=400,
                )
            skill = db.get(AISkill, skill_version.skill_id)
            package = db.scalar(
                select(AISkillPackage).where(AISkillPackage.skill_version_id == skill_version.id)
            )
            if (
                skill is None
                or skill.project_id != project_id
                or skill.code != node.get("skill")
                or package is None
                or binding.package_fingerprint != skill_version.package_fingerprint
                or package.package_fingerprint != skill_version.package_fingerprint
                or skill_version.status not in {"PUBLISHED", "DEPRECATED"}
            ):
                raise AppError(
                    code="RUN_SKILL_BINDING_INVALID",
                    message=f"节点 {node_id} 的 Skill 绑定完整性校验失败",
                    status_code=400,
                )

            for relative_path, content in package.files_snapshot.items():
                namespaced_path = f"skills/{skill.code}/{relative_path}"
                existing_content = package_files.get(namespaced_path)
                if existing_content is not None and existing_content != content:
                    raise AppError(
                        code="RUN_PACKAGE_INTEGRITY_ERROR",
                        message=f"能力包与 Skill 包文件冲突: {namespaced_path}",
                        status_code=400,
                    )
                package_files[namespaced_path] = content

            binding_snapshot[node_id] = {
                "skillId": str(skill.id),
                "skillCode": skill.code,
                "skillVersionId": str(skill_version.id),
                "version": skill_version.version,
                "packageFingerprint": skill_version.package_fingerprint,
            }
            visited_bindings.add(node_id)

        unexpected_bindings = set(binding_by_node).difference(visited_bindings)
        if unexpected_bindings:
            raise AppError(
                code="RUN_SKILL_BINDING_INVALID",
                message=(
                    "能力版本包含未对应 Workflow SKILL 节点的绑定: "
                    f"{', '.join(sorted(unexpected_bindings))}"
                ),
                status_code=400,
            )

        return {
            "packageFiles": package_files,
            "skillBindings": binding_snapshot,
        }

    @staticmethod
    def _is_safe_path(path: str) -> bool:
        if not path or path.startswith("/") or "\\" in path:
            return False
        pure_path = PurePosixPath(path)
        if any(part in {"", ".", ".."} for part in pure_path.parts):
            return False
        return str(pure_path) == path

    @staticmethod
    def _is_allowed_package_path(path: str) -> bool:
        if path in _ALLOWED_ROOT_FILES or path == "agents/openai.yaml":
            return True
        parts = PurePosixPath(path).parts
        return (
            len(parts) >= 2
            and parts[0] in {"examples", "evaluations"}
            and PurePosixPath(path).suffix.lower() in _ALLOWED_SUPPORT_SUFFIXES
        )

    @staticmethod
    def _fingerprint(file_map: dict[str, str]) -> str:
        digest = hashlib.sha256()
        for path in sorted(file_map):
            digest.update(path.encode("utf-8"))
            digest.update(b"\0")
            digest.update(file_map[path].encode("utf-8"))
            digest.update(b"\0")
        return digest.hexdigest()

    @staticmethod
    def _validate_skill_manifest(
        skill_info: dict[str, Any],
        file_map: dict[str, str],
        issues: list[str],
    ) -> None:
        code = skill_info.get("id")
        if not isinstance(code, str) or not _SKILL_CODE_PATTERN.fullmatch(code):
            issues.append("skill.id 必须使用小写字母、数字和单连字符")
        version = skill_info.get("version")
        if not isinstance(version, str) or not _SEMVER_PATTERN.fullmatch(version):
            issues.append("skill.version 必须是语义化版本号")
        for field in ("name", "description"):
            value = skill_info.get(field)
            if not isinstance(value, str) or not value.strip():
                issues.append(f"skill.{field} 必须是非空字符串")

        model_policy = skill_info.get("model_policy")
        if model_policy not in _MODEL_POLICIES:
            issues.append(f"skill.model_policy 不受支持: {model_policy}")
        side_effect_level = skill_info.get("side_effect_level")
        if side_effect_level not in _SIDE_EFFECT_LEVELS:
            issues.append(f"skill.side_effect_level 不受支持: {side_effect_level}")

        for field in ("allowed_tools", "required_permissions"):
            value = skill_info.get(field)
            if not isinstance(value, list) or not all(
                isinstance(item, str) and item for item in value
            ):
                issues.append(f"skill.{field} 必须是字符串数组")
        allowed_tools = skill_info.get("allowed_tools")
        if isinstance(allowed_tools, list):
            unknown_tools = sorted(set(allowed_tools).difference(_REGISTERED_TOOLS))
            if unknown_tools:
                issues.append(f"skill.allowed_tools 引用了未注册 Tool: {', '.join(unknown_tools)}")
        required_permissions = skill_info.get("required_permissions")
        if isinstance(required_permissions, list):
            unknown_permissions = sorted(
                set(required_permissions).difference(_ALLOWED_REQUIRED_PERMISSIONS)
            )
            if unknown_permissions:
                issues.append(
                    f"skill.required_permissions 包含未授权权限: {', '.join(unknown_permissions)}"
                )

        for field in ("prompt", "input_schema", "output_schema"):
            path = skill_info.get(field)
            if not isinstance(path, str) or not SkillRegistryService._is_safe_path(path):
                issues.append(f"skill.{field} 必须是安全的相对路径")
            elif path not in file_map:
                issues.append(f"skill.{field} 声明的文件不存在: {path}")
            elif field == "prompt" and not file_map[path].strip():
                issues.append("skill.prompt 文件不能为空")

    @staticmethod
    def _load_schema(
        label: str,
        path: Any,
        file_map: dict[str, str],
        issues: list[str],
    ) -> dict[str, Any] | None:
        if not isinstance(path, str) or path not in file_map:
            return None
        try:
            schema = json.loads(file_map[path])
            if not isinstance(schema, dict):
                raise ValueError("根节点必须是对象")
            Draft7Validator.check_schema(schema)
            if SkillRegistryService._contains_external_schema_ref(schema):
                raise ValueError("禁止使用外部 $ref，只允许当前 Schema 内的 # 引用")
            return schema
        except (json.JSONDecodeError, SchemaError, ValueError) as exc:
            issues.append(f"{label} 非法: {exc!s}")
            return None

    @staticmethod
    def _contains_external_schema_ref(value: Any) -> bool:
        if isinstance(value, dict):
            ref = value.get("$ref")
            if isinstance(ref, str) and not ref.startswith("#"):
                return True
            return any(
                SkillRegistryService._contains_external_schema_ref(item) for item in value.values()
            )
        if isinstance(value, list):
            return any(SkillRegistryService._contains_external_schema_ref(item) for item in value)
        return False

    @staticmethod
    def _validate_skill_md(
        content: str | None,
        *,
        expected_name: Any,
        issues: list[str],
    ) -> None:
        if not content:
            return
        if not content.startswith("---\n"):
            issues.append("SKILL.md 缺少 YAML frontmatter")
            return
        end_index = content.find("\n---\n", 4)
        if end_index < 0:
            issues.append("SKILL.md frontmatter 未闭合")
            return
        try:
            metadata = safe_yaml_load(content[4:end_index])
        except Exception as exc:
            issues.append(f"SKILL.md frontmatter 解析失败: {exc!s}")
            return
        if not isinstance(metadata, dict):
            issues.append("SKILL.md frontmatter 必须是对象")
            return
        unknown_fields = set(metadata).difference({"name", "description"})
        if unknown_fields:
            issues.append(f"SKILL.md frontmatter 包含未知字段: {', '.join(sorted(unknown_fields))}")
        if metadata.get("name") != expected_name:
            issues.append("SKILL.md name 必须与 manifest skill.id 一致")
        description = metadata.get("description")
        if not isinstance(description, str) or not description.strip():
            issues.append("SKILL.md description 必须是非空字符串")

    @staticmethod
    def _sync_response(
        status: str,
        skill: AISkill,
        version: AISkillVersion,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "skillId": str(skill.id),
            "versionId": str(version.id),
            "skillCode": skill.code,
            "version": version.version,
            "packageFingerprint": version.package_fingerprint,
        }
