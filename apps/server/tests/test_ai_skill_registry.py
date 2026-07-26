import json
import textwrap
import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    AICapability,
    AICapabilityPackage,
    AICapabilitySkillBinding,
    AICapabilityVersion,
    AISkill,
    AISkillPackage,
    AISkillVersion,
    AuditEvent,
    Project,
    ProjectMember,
    User,
)
from testweave.main import create_app
from testweave.modules.ai_capability.external_agent.token_service import (
    ExternalAgentTokenService,
)
from testweave.modules.ai_capability.runtime.config import AIRuntimeSettings
from testweave.modules.ai_capability.runtime.schemas import AIRunCreateRequest
from testweave.modules.ai_capability.runtime.service import AIRuntimeService
from testweave.modules.ai_capability.schemas import FileMapping
from testweave.modules.ai_skill.service import SkillRegistryService
from testweave.modules.ai_test_design.builtin_capability import (
    BuiltinAiTestDesignCapabilityService,
)


def _skill_files(
    *,
    code: str = "requirement-analysis",
    version: str = "1.0.0",
    prompt: str = "只根据输入事实生成需求分析。",
    output_schema: dict[str, Any] | None = None,
) -> list[FileMapping]:
    output_schema = output_schema or {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {"result": {"type": "string"}},
        "required": ["result"],
        "additionalProperties": False,
    }
    input_schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {"requirement": {"type": "string"}},
        "required": ["requirement"],
        "additionalProperties": False,
    }
    manifest = textwrap.dedent(
        f"""\
        protocol_version: "1.0"
        skill:
          id: "{code}"
          version: "{version}"
          name: "需求分析"
          description: "生成待人工确认的结构化需求分析候选稿。"
          prompt: "prompt.md"
          input_schema: "input.schema.json"
          output_schema: "output.schema.json"
          model_policy: "quality_first"
          allowed_tools: []
          required_permissions:
            - "project.read"
          side_effect_level: "L1"
        """
    )
    skill_md = textwrap.dedent(
        f"""\
        ---
        name: {code}
        description: 分析测试需求并生成结构化候选稿；当 TestWeave 项目需要需求分析时使用。
        ---

        # 需求分析

        读取 prompt.md 和 Schema，校验后只提交 Candidate。
        """
    )
    return [
        FileMapping(path="manifest.yaml", content=manifest),
        FileMapping(path="SKILL.md", content=skill_md),
        FileMapping(path="prompt.md", content=prompt),
        FileMapping(path="input.schema.json", content=json.dumps(input_schema)),
        FileMapping(path="output.schema.json", content=json.dumps(output_schema)),
    ]


@pytest.fixture
def skill_context(db: Session) -> dict[str, Any]:
    admin = User(
        email=f"skill_{uuid.uuid4().hex[:8]}@testweave.com",
        username=f"skill_{uuid.uuid4().hex[:8]}",
        display_name="Skill Admin",
        hashed_password="dummy_hash",
        status="active",
    )
    db.add(admin)
    db.flush()

    project = Project(
        name="Skill Project",
        key=f"SK{uuid.uuid4().hex[:6]}".upper(),
        owner_id=admin.id,
    )
    db.add(project)
    db.flush()
    db.add(
        ProjectMember(
            project_id=project.id,
            user_id=admin.id,
            role_id="project_admin",
        )
    )
    db.commit()
    return {"admin": admin, "project": project}


def test_sync_skill_draft_snapshots_package_and_replays_idempotently(
    db: Session,
    skill_context: dict[str, Any],
) -> None:
    admin = skill_context["admin"]
    project = skill_context["project"]
    files = _skill_files()

    first = SkillRegistryService.sync_draft(
        db=db,
        project_id=project.id,
        user_id=admin.id,
        effective_scopes=["skill:sync"],
        files=files,
    )
    replay = SkillRegistryService.sync_draft(
        db=db,
        project_id=project.id,
        user_id=admin.id,
        effective_scopes=["skill:sync"],
        files=files,
    )

    assert first["status"] == "SYNCED"
    assert replay["status"] == "UNCHANGED"
    assert replay["versionId"] == first["versionId"]

    skill = db.scalar(
        select(AISkill).where(
            AISkill.project_id == project.id,
            AISkill.code == "requirement-analysis",
        )
    )
    assert skill is not None
    assert skill.name == "需求分析"
    assert skill.maintainer_id == admin.id
    assert skill.current_published_version_id is None

    versions = list(
        db.scalars(select(AISkillVersion).where(AISkillVersion.skill_id == skill.id)).all()
    )
    assert len(versions) == 1
    assert versions[0].status == "SYNCED_DRAFT"
    assert versions[0].package_fingerprint == first["packageFingerprint"]
    assert versions[0].input_schema["type"] == "object"
    assert versions[0].output_schema["required"] == ["result"]

    package = db.scalar(
        select(AISkillPackage).where(AISkillPackage.skill_version_id == versions[0].id)
    )
    assert package is not None
    assert package.files_snapshot["prompt.md"] == "只根据输入事实生成需求分析。"
    assert package.validation_report["valid"] is True


def test_sync_skill_rejects_same_version_with_changed_content(
    db: Session,
    skill_context: dict[str, Any],
) -> None:
    admin = skill_context["admin"]
    project = skill_context["project"]
    SkillRegistryService.sync_draft(
        db=db,
        project_id=project.id,
        user_id=admin.id,
        effective_scopes=["skill:sync"],
        files=_skill_files(),
    )

    with pytest.raises(AppError) as exc_info:
        SkillRegistryService.sync_draft(
            db=db,
            project_id=project.id,
            user_id=admin.id,
            effective_scopes=["skill:sync"],
            files=_skill_files(prompt="同版本被修改的提示词"),
        )

    assert exc_info.value.code == "SKILL_VERSION_CONFLICT"
    assert exc_info.value.status_code == 409


@pytest.mark.parametrize(
    ("files", "issue_fragment"),
    [
        (
            [
                FileMapping(path="../manifest.yaml", content="protocol_version: '1.0'"),
            ],
            "路径",
        ),
        (
            [
                FileMapping(
                    path=(" manifest.yaml" if file.path == "manifest.yaml" else file.path),
                    content=file.content,
                )
                for file in _skill_files()
            ],
            "不规范",
        ),
        (
            [
                *_skill_files(),
                FileMapping(path="scripts/run.py", content="print('must never execute')"),
            ],
            "不受支持",
        ),
        (
            _skill_files(
                output_schema={
                    "$schema": "http://json-schema.org/draft-07/schema#",
                    "type": "not-a-json-schema-type",
                }
            ),
            "output Schema",
        ),
        (
            _skill_files(
                output_schema={
                    "$schema": "http://json-schema.org/draft-07/schema#",
                    "$ref": "https://untrusted.example/schema.json",
                }
            ),
            "外部 $ref",
        ),
    ],
)
def test_sync_skill_rejects_unsafe_path_and_invalid_schema(
    db: Session,
    skill_context: dict[str, Any],
    files: list[FileMapping],
    issue_fragment: str,
) -> None:
    with pytest.raises(AppError) as exc_info:
        SkillRegistryService.sync_draft(
            db=db,
            project_id=skill_context["project"].id,
            user_id=skill_context["admin"].id,
            effective_scopes=["skill:sync"],
            files=files,
        )

    assert exc_info.value.code == "SKILL_PACKAGE_INVALID"
    assert issue_fragment in " ".join(exc_info.value.details["issues"])


def test_sync_skill_requires_dedicated_scope_and_isolates_projects(
    db: Session,
    skill_context: dict[str, Any],
) -> None:
    admin = skill_context["admin"]
    first_project = skill_context["project"]

    with pytest.raises(AppError) as exc_info:
        SkillRegistryService.sync_draft(
            db=db,
            project_id=first_project.id,
            user_id=admin.id,
            effective_scopes=["revision:candidate"],
            files=_skill_files(),
        )
    assert exc_info.value.code == "SCOPE_PERMISSION_DENIED"

    second_project = Project(
        name="Second Skill Project",
        key=f"S2{uuid.uuid4().hex[:6]}".upper(),
        owner_id=admin.id,
    )
    db.add(second_project)
    db.flush()
    db.add(
        ProjectMember(
            project_id=second_project.id,
            user_id=admin.id,
            role_id="project_admin",
        )
    )
    db.commit()

    first = SkillRegistryService.sync_draft(
        db=db,
        project_id=first_project.id,
        user_id=admin.id,
        effective_scopes=["skill:sync"],
        files=_skill_files(),
    )
    second = SkillRegistryService.sync_draft(
        db=db,
        project_id=second_project.id,
        user_id=admin.id,
        effective_scopes=["skill:sync"],
        files=_skill_files(),
    )

    assert first["skillId"] != second["skillId"]
    assert db.scalar(
        select(AISkill).where(AISkill.id == uuid.UUID(first["skillId"]))
    ).project_id == (first_project.id)
    assert db.scalar(
        select(AISkill).where(AISkill.id == uuid.UUID(second["skillId"]))
    ).project_id == (second_project.id)


def test_sync_skill_rejects_unregistered_tools_and_permissions(
    db: Session,
    skill_context: dict[str, Any],
) -> None:
    files = _skill_files()
    manifest_file = next(file for file in files if file.path == "manifest.yaml")
    manifest_file.content = manifest_file.content.replace(
        "allowed_tools: []",
        'allowed_tools:\n    - "shell.execute"',
    ).replace(
        '    - "project.read"',
        '    - "project.read"\n    - "database.admin"',
    )

    with pytest.raises(AppError) as exc_info:
        SkillRegistryService.sync_draft(
            db=db,
            project_id=skill_context["project"].id,
            user_id=skill_context["admin"].id,
            effective_scopes=["skill:sync"],
            files=files,
        )

    assert exc_info.value.code == "SKILL_PACKAGE_INVALID"
    issues = " ".join(exc_info.value.details["issues"])
    assert "未注册 Tool" in issues
    assert "未授权权限" in issues


def test_publish_skill_version_sets_project_pointer_and_audits(
    db: Session,
    skill_context: dict[str, Any],
) -> None:
    admin = skill_context["admin"]
    project = skill_context["project"]
    synced = SkillRegistryService.sync_draft(
        db=db,
        project_id=project.id,
        user_id=admin.id,
        effective_scopes=["skill:sync"],
        files=_skill_files(),
    )

    published = SkillRegistryService.publish_version(
        db=db,
        project_id=project.id,
        skill_id=uuid.UUID(synced["skillId"]),
        version_id=uuid.UUID(synced["versionId"]),
        actor_id=admin.id,
        request_id="req-publish-skill",
    )

    assert published["status"] == "PUBLISHED"
    skill = db.get(AISkill, uuid.UUID(synced["skillId"]))
    version = db.get(AISkillVersion, uuid.UUID(synced["versionId"]))
    assert skill.current_published_version_id == version.id
    assert version.status == "PUBLISHED"
    assert version.published_at is not None

    event = db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "ai_skill_version_published",
            AuditEvent.object_id == str(version.id),
        )
    )
    assert event is not None
    assert event.project_id == project.id


def test_capability_binding_freezes_skill_version_and_runtime_materials(
    db: Session,
    skill_context: dict[str, Any],
) -> None:
    admin = skill_context["admin"]
    project = skill_context["project"]
    synced = SkillRegistryService.sync_draft(
        db=db,
        project_id=project.id,
        user_id=admin.id,
        effective_scopes=["skill:sync"],
        files=_skill_files(prompt="VERSIONED_PROMPT"),
    )
    SkillRegistryService.publish_version(
        db=db,
        project_id=project.id,
        skill_id=uuid.UUID(synced["skillId"]),
        version_id=uuid.UUID(synced["versionId"]),
        actor_id=admin.id,
        request_id="publish-before-bind",
    )

    capability = AICapability(
        namespace=f"project/{project.id}",
        code="ai-test-design-workbench",
        name="AI 测试设计工作台",
        category="TEST_DESIGN_WORKBENCH",
        scope="PROJECT",
        project_id=project.id,
        status="ACTIVE",
    )
    db.add(capability)
    db.flush()
    workflow = {
        "nodes": {
            "requirement_analysis": {
                "type": "SKILL",
                "skill": "requirement-analysis",
                "skill_version_id": synced["versionId"],
                "input": "capability.input",
            }
        }
    }
    capability_version = AICapabilityVersion(
        capability_id=capability.id,
        version="1.0.0",
        status="PUBLISHED",
        package_fingerprint="capability-fingerprint",
        compatibility_level="PLATFORM_NATIVE",
        workflow_snapshot=workflow,
        input_schema={"type": "object"},
        created_source="SKILL_REGISTRY",
        created_by=admin.id,
    )
    db.add(capability_version)
    db.flush()
    db.add(
        AICapabilityPackage(
            capability_version_id=capability_version.id,
            package_fingerprint="capability-fingerprint",
            validation_report={"valid": True},
            files_snapshot={"workflow.json": workflow},
        )
    )
    capability.current_published_version_id = capability_version.id
    db.flush()

    bindings = SkillRegistryService.bind_capability_version(
        db=db,
        project_id=project.id,
        capability_version_id=capability_version.id,
        node_skill_versions={
            "requirement_analysis": uuid.UUID(synced["versionId"]),
        },
    )
    materials = SkillRegistryService.resolve_runtime_materials(
        db=db,
        project_id=project.id,
        capability_version_id=capability_version.id,
        workflow_snapshot=workflow,
        capability_files={"workflow.json": workflow},
    )

    assert len(bindings) == 1
    binding = db.scalar(
        select(AICapabilitySkillBinding).where(
            AICapabilitySkillBinding.capability_version_id == capability_version.id
        )
    )
    assert binding is not None
    assert binding.skill_version_id == uuid.UUID(synced["versionId"])
    assert materials["packageFiles"]["skills/requirement-analysis/prompt.md"] == (
        "VERSIONED_PROMPT"
    )
    assert materials["skillBindings"]["requirement_analysis"] == {
        "skillId": synced["skillId"],
        "skillCode": "requirement-analysis",
        "skillVersionId": synced["versionId"],
        "version": "1.0.0",
        "packageFingerprint": synced["packageFingerprint"],
    }

    run, created = AIRuntimeService.create_run(
        db=db,
        project_id=project.id,
        capability_id=capability.id,
        request=AIRunCreateRequest(input={}),
        idempotency_key="skill-binding-runtime",
        actor_id=admin.id,
        actor_permissions={"agent.use"},
        runtime_settings=AIRuntimeSettings(enabled=True),
    )
    assert created is True
    assert run.execution_snapshot["skill_bindings"] == materials["skillBindings"]
    assert (
        run.execution_snapshot["package_files"]["skills/requirement-analysis/prompt.md"]
        == "VERSIONED_PROMPT"
    )


def test_declared_skill_version_requires_matching_binding(
    db: Session,
    skill_context: dict[str, Any],
) -> None:
    admin = skill_context["admin"]
    project = skill_context["project"]
    capability = AICapability(
        namespace=f"project/{project.id}",
        code="unbound-workbench",
        name="Unbound",
        category="TEST_DESIGN_WORKBENCH",
        scope="PROJECT",
        project_id=project.id,
        status="ACTIVE",
    )
    db.add(capability)
    db.flush()
    version = AICapabilityVersion(
        capability_id=capability.id,
        version="1.0.0",
        status="PUBLISHED",
        package_fingerprint="cap-fingerprint",
        compatibility_level="PLATFORM_NATIVE",
        workflow_snapshot={},
        input_schema={"type": "object"},
        created_source="SKILL_REGISTRY",
        created_by=admin.id,
    )
    db.add(version)
    db.commit()
    declared_id = uuid.uuid4()

    with pytest.raises(AppError) as exc_info:
        SkillRegistryService.resolve_runtime_materials(
            db=db,
            project_id=project.id,
            capability_version_id=version.id,
            workflow_snapshot={
                "nodes": {
                    "analysis": {
                        "type": "SKILL",
                        "skill": "requirement-analysis",
                        "skill_version_id": str(declared_id),
                    }
                }
            },
            capability_files={},
        )

    assert exc_info.value.code == "RUN_SKILL_BINDING_INVALID"


def test_workbench_capability_requires_and_pins_four_published_project_skills(
    db: Session,
    skill_context: dict[str, Any],
) -> None:
    admin = skill_context["admin"]
    project = skill_context["project"]

    with pytest.raises(AppError) as missing_exc:
        BuiltinAiTestDesignCapabilityService.ensure_published(
            db,
            actor_id=admin.id,
            project_id=project.id,
        )
    assert missing_exc.value.code == "AI_TEST_DESIGN_SKILLS_NOT_READY"
    assert sorted(missing_exc.value.details["missingSkillCodes"]) == [
        "requirement-analysis",
        "test-case-generation",
        "test-case-review",
        "test-point-generation",
    ]

    synced_by_code = {}
    for code in [
        "requirement-analysis",
        "test-point-generation",
        "test-case-generation",
        "test-case-review",
    ]:
        synced = SkillRegistryService.sync_draft(
            db=db,
            project_id=project.id,
            user_id=admin.id,
            effective_scopes=["skill:sync"],
            files=_skill_files(code=code, prompt=f"PROMPT::{code}"),
        )
        SkillRegistryService.publish_version(
            db=db,
            project_id=project.id,
            skill_id=uuid.UUID(synced["skillId"]),
            version_id=uuid.UUID(synced["versionId"]),
            actor_id=admin.id,
            request_id=f"publish-{code}",
        )
        synced_by_code[code] = synced

    capability = BuiltinAiTestDesignCapabilityService.ensure_published(
        db,
        actor_id=admin.id,
        project_id=project.id,
    )
    version = db.get(AICapabilityVersion, capability.current_published_version_id)
    package = db.scalar(
        select(AICapabilityPackage).where(AICapabilityPackage.capability_version_id == version.id)
    )
    bindings = list(
        db.scalars(
            select(AICapabilitySkillBinding).where(
                AICapabilitySkillBinding.capability_version_id == version.id
            )
        ).all()
    )

    assert capability.scope == "PROJECT"
    assert capability.project_id == project.id
    assert version.created_source == "SKILL_REGISTRY"
    assert len(bindings) == 4
    assert not any(path.startswith("skills/") for path in package.files_snapshot)
    expected_node_versions = {
        "requirement_analysis": synced_by_code["requirement-analysis"]["versionId"],
        "test_points": synced_by_code["test-point-generation"]["versionId"],
        "test_cases": synced_by_code["test-case-generation"]["versionId"],
        "case_review": synced_by_code["test-case-review"]["versionId"],
    }
    for node_id, version_id in expected_node_versions.items():
        assert version.workflow_snapshot["nodes"][node_id]["skill_version_id"] == version_id
        assert version.workflow_snapshot["nodes"][node_id]["input_schema"]["type"] == "object"


@pytest.mark.anyio
async def test_skill_registry_external_sync_and_internal_publish_apis(
    db: Session,
    skill_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    from testweave.api.dependencies.auth import get_current_user
    from testweave.api.dependencies.database import get_db
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()
    admin = skill_context["admin"]
    project = skill_context["project"]
    _token, raw_token = ExternalAgentTokenService.create_token(
        db,
        name="Skill Sync Token",
        project_id=project.id,
        user_id=admin.id,
        scopes=["skill:sync"],
    )

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: admin

    payload = {
        "files": [
            {"path": file.path, "content": file.content}
            for file in _skill_files(code="test-point-generation")
        ]
    }
    headers = {"Authorization": f"Bearer {raw_token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        sync_response = await client.post(
            "/external/v1/skills/sync-draft",
            json=payload,
            headers=headers,
        )
        assert sync_response.status_code == 200, sync_response.text
        synced = sync_response.json()

        list_response = await client.get(f"/api/v1/projects/{project.id}/skills")
        assert list_response.status_code == 200, list_response.text
        assert [item["code"] for item in list_response.json()["items"]] == ["test-point-generation"]
        assert list_response.json()["items"][0]["maintainerId"] == str(admin.id)

        publish_response = await client.post(
            f"/api/v1/projects/{project.id}/skills/{synced['skillId']}"
            f"/versions/{synced['versionId']}/publish"
        )
        assert publish_response.status_code == 200, publish_response.text
        assert publish_response.json()["status"] == "PUBLISHED"

        version_response = await client.get(
            f"/api/v1/projects/{project.id}/skills/{synced['skillId']}"
            f"/versions/{synced['versionId']}"
        )
        assert version_response.status_code == 200, version_response.text
        version_body = version_response.json()
        assert version_body["version"] == "1.0.0"
        assert version_body["files"] == sorted(
            ["SKILL.md", "input.schema.json", "manifest.yaml", "output.schema.json", "prompt.md"]
        )

    app.dependency_overrides.clear()
    get_external_agent_config.cache_clear()


@pytest.mark.anyio
async def test_external_skill_sync_rejects_token_without_skill_scope(
    db: Session,
    skill_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    from testweave.api.dependencies.database import get_db
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()
    admin = skill_context["admin"]
    project = skill_context["project"]
    _token, raw_token = ExternalAgentTokenService.create_token(
        db,
        name="Candidate Only Token",
        project_id=project.id,
        user_id=admin.id,
        scopes=["revision:candidate"],
    )

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/external/v1/skills/sync-draft",
            json={
                "files": [{"path": file.path, "content": file.content} for file in _skill_files()]
            },
            headers={"Authorization": f"Bearer {raw_token}"},
        )
        assert response.status_code == 403
        assert response.json()["code"] == "SCOPE_PERMISSION_DENIED"

    app.dependency_overrides.clear()
    get_external_agent_config.cache_clear()


def test_skill_sync_scope_tracks_test_lead_agent_manage_permission(
    db: Session,
    skill_context: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TESTWEAVE_EXTERNAL_AGENT__ENABLED", "true")
    from testweave.modules.ai_capability.config import get_external_agent_config

    get_external_agent_config.cache_clear()
    project = skill_context["project"]
    lead = User(
        email=f"lead_{uuid.uuid4().hex[:8]}@testweave.com",
        username=f"lead_{uuid.uuid4().hex[:8]}",
        display_name="Test Lead",
        hashed_password="dummy_hash",
        status="active",
    )
    db.add(lead)
    db.flush()
    membership = ProjectMember(
        project_id=project.id,
        user_id=lead.id,
        role_id="test_lead",
    )
    db.add(membership)
    db.commit()
    _token, raw_token = ExternalAgentTokenService.create_token(
        db,
        name="Lead Skill Token",
        project_id=project.id,
        user_id=lead.id,
        scopes=["skill:sync"],
    )

    _token_obj, _user, role, effective_scopes = ExternalAgentTokenService.authenticate_token(
        db, raw_token
    )
    assert role == "ADMIN"
    assert "skill:sync" in effective_scopes

    membership.role_id = "test_member"
    db.commit()
    _token_obj, _user, downgraded_role, downgraded_scopes = (
        ExternalAgentTokenService.authenticate_token(db, raw_token)
    )
    assert downgraded_role == "EDITOR"
    assert "skill:sync" not in downgraded_scopes
    get_external_agent_config.cache_clear()
