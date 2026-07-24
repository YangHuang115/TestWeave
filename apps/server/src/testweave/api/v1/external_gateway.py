import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from testweave.api.dependencies.database import get_db
from testweave.core.errors import AppError
from testweave.db.models import Requirement
from testweave.modules.ai_capability.external_agent.artifact_schema_validator import (
    ArtifactSchemaValidator,
)
from testweave.modules.ai_capability.external_agent.candidate_submission_service import (
    CandidateSubmissionService,
)
from testweave.modules.ai_capability.external_agent.draft_sync_service import (
    DraftSyncService,
)
from testweave.modules.ai_capability.external_agent.idempotency_service import (
    IdempotencyService,
)
from testweave.modules.ai_capability.external_agent.token_service import (
    ExternalAgentTokenService,
)
from testweave.modules.ai_capability.external_agent.workbench_handshake_service import (
    WorkbenchHandshakeService,
)
from testweave.modules.ai_capability.external_agent.workbench_schemas import (
    ResolveWorkbenchRequest,
    ResolveWorkbenchResponse,
)
from testweave.modules.ai_capability.external_agent.workspace_spec_service import (
    WorkspaceSpecService,
)

router = APIRouter(prefix="/external/v1", tags=["External Agent Client Gateway v1"])
READ_SCOPES = ["test_task.read", "requirement.read", "workspace:spec", "revision:candidate"]
WORKBENCH_REQUIRED_SCOPES = frozenset({"test_task.read", "requirement.read"})


class SessionCheckResponse(BaseModel):
    valid: bool
    tokenId: str
    tokenName: str
    tokenPrefix: str
    projectId: str
    userId: str
    userRole: str
    grantedScopes: list[str]
    effectiveScopes: list[str]
    expiresAt: str | None


@router.get("/session", summary="外部 Client Token 状态与生效权限交集校验")
async def check_external_session(
    authorization: str | None = Header(None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> SessionCheckResponse:
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError(
            code="INVALID_EXTERNAL_TOKEN",
            message="缺少 Authorization Header 或 Token 格式错误",
            status_code=401,
        )

    raw_token = authorization.removeprefix("Bearer ").strip()
    token, user, user_role, effective_scopes = ExternalAgentTokenService.authenticate_token(
        db, raw_token
    )

    return SessionCheckResponse(
        valid=True,
        tokenId=str(token.id),
        tokenName=token.name,
        tokenPrefix=token.token_prefix,
        projectId=str(token.project_id),
        userId=str(user.id),
        userRole=user_role,
        grantedScopes=token.scopes,
        effectiveScopes=effective_scopes,
        expiresAt=token.expires_at.isoformat() if token.expires_at else None,
    )


@router.post(
    "/workbench/resolve",
    summary="根据外接 Agent 首句解析只读工作台并返回直接执行入口",
    response_model=ResolveWorkbenchResponse,
)
async def resolve_external_workbench(
    body: ResolveWorkbenchRequest,
    authorization: str | None = Header(None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> ResolveWorkbenchResponse:
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError(
            code="INVALID_EXTERNAL_TOKEN",
            message="缺少 Authorization Header 或 Token 格式错误",
            status_code=401,
        )

    raw_token = authorization.removeprefix("Bearer ").strip()
    token, user, _role, effective_scopes = ExternalAgentTokenService.authenticate_token(
        db, raw_token
    )
    missing_scopes = sorted(WORKBENCH_REQUIRED_SCOPES.difference(effective_scopes))
    if missing_scopes:
        raise AppError(
            code="SCOPE_PERMISSION_DENIED",
            message=f"Lack required workbench scopes ({' | '.join(missing_scopes)})",
            status_code=403,
        )

    return ResolveWorkbenchResponse.model_validate(
        WorkbenchHandshakeService.resolve(
            db=db,
            project_id=token.project_id,
            user_id=user.id,
            message=body.message,
        )
    )


@router.get("/token/scopes", summary="获取受支持的 External Token Scope 字典")
async def list_supported_token_scopes() -> dict[str, Any]:
    return {
        "scopes": ExternalAgentTokenService.get_supported_scopes(),
    }


@router.get("/workspace/spec", summary="拉取 External Agent 代码生成与隔离规范 Spec")
async def get_workspace_spec(
    targetId: uuid.UUID | None = Query(None),
    authorization: str | None = Header(None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError(
            code="INVALID_EXTERNAL_TOKEN",
            message="缺少 Authorization Header 或 Token 格式错误",
            status_code=401,
        )

    raw_token = authorization.removeprefix("Bearer ").strip()
    token, user, _role, effective_scopes = ExternalAgentTokenService.authenticate_token(
        db, raw_token
    )

    spec = WorkspaceSpecService.generate_workspace_spec(
        db=db,
        target_id=targetId,
        effective_scopes=effective_scopes,
        project_id=token.project_id,
        user_id=user.id,
    )
    return spec


class ValidateArtifactRequest(BaseModel):
    artifactType: str
    payload: dict[str, Any]


@router.get("/artifact/schemas", summary="获取受支持的 Candidate Artifact 双类型 Schema 字典")
async def list_artifact_schemas() -> dict[str, Any]:
    types = ArtifactSchemaValidator.get_supported_types()
    schemas = {t: ArtifactSchemaValidator.get_schema(t) for t in types}
    return {
        "supportedTypes": types,
        "schemas": schemas,
    }


@router.post("/artifact/validate", summary="预校验 External Agent 候选 Artifact 结构合规性")
async def validate_artifact_payload(
    body: ValidateArtifactRequest,
) -> dict[str, Any]:
    validated = ArtifactSchemaValidator.validate_artifact(
        artifact_type=body.artifactType,
        payload=body.payload,
    )
    return {
        "valid": True,
        "artifactType": body.artifactType,
        "validatedPayload": validated,
    }


class SubmitCandidateRequest(BaseModel):
    capabilityId: uuid.UUID | None = Field(None, alias="capability_id")
    taskId: uuid.UUID | None = Field(None, alias="task_id")
    taskKey: str | None = Field(None, alias="task_key")
    requirementId: uuid.UUID | None = Field(None, alias="requirement_id")
    requirementKey: str | None = Field(None, alias="requirement_key")
    artifactType: str = Field(..., alias="artifact_type")
    payload: dict[str, Any]
    summary: str | None = None
    autoPublish: Literal[False] = Field(False, alias="auto_publish")
    idempotencyKey: str | None = Field(None, alias="idempotencyKey")

    model_config = ConfigDict(populate_by_name=True)


class RegisterAttachmentRequest(BaseModel):
    submissionId: uuid.UUID
    fileName: str
    fileSize: int
    mimeType: str
    checksum: str | None = None


@router.post("/revision/candidates", summary="外接 Agent Client 提交 Candidate Revision 候选结果")
async def submit_candidate_revision(
    body: SubmitCandidateRequest,
    response: Response,
    idempotency_header: str | None = Header(None, alias="Idempotency-Key"),
    authorization: str | None = Header(None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError(
            code="INVALID_EXTERNAL_TOKEN",
            message="缺少 Authorization Header 或 Token 格式错误",
            status_code=401,
        )

    raw_token = authorization.removeprefix("Bearer ").strip()
    token, user, _role, effective_scopes = ExternalAgentTokenService.authenticate_token(
        db, raw_token
    )

    # 1. 解析并一致性校验幂等键
    idempotency_key = IdempotencyService.resolve_key(idempotency_header, body.idempotencyKey)

    # 2. 计算 Request Hash
    endpoint = "/external/v1/revision/candidates"
    hash_payload = {
        "capabilityId": str(body.capabilityId) if body.capabilityId else None,
        "taskId": str(body.taskId) if body.taskId else None,
        "taskKey": body.taskKey,
        "requirementId": str(body.requirementId) if body.requirementId else None,
        "requirementKey": body.requirementKey,
        "artifactType": body.artifactType,
        "payload": body.payload,
        "autoPublish": body.autoPublish,
        "summary": body.summary,
    }
    request_hash = IdempotencyService.compute_request_hash(hash_payload)

    # 3. 检查幂等击中（重放/防重）
    if idempotency_key:
        cached_response = IdempotencyService.check_existing(
            db=db,
            project_id=token.project_id,
            endpoint=endpoint,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if cached_response is not None:
            response.headers["Idempotency-Replay"] = "true"
            return cached_response

    # 4. 首次提交处理
    result = CandidateSubmissionService.submit_candidate_revision(
        db=db,
        token_project_id=token.project_id,
        user_id=user.id,
        effective_scopes=effective_scopes,
        capability_id=body.capabilityId,
        task_id=body.taskId,
        task_key=body.taskKey,
        requirement_id=body.requirementId,
        requirement_key=body.requirementKey,
        artifact_type=body.artifactType,
        payload=body.payload,
        auto_publish=body.autoPublish,
        summary=body.summary,
    )

    # 5. 持久化记录响应到 idempotency_keys 表
    if idempotency_key:
        IdempotencyService.record_response(
            db=db,
            project_id=token.project_id,
            endpoint=endpoint,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            response_json=result,
        )

    return result


@router.get("/candidates/{submissionId}", summary="外接 Agent Client 查询 Candidate 提交历史及状态")
async def get_external_candidate_submission_endpoint(
    submissionId: uuid.UUID,
    authorization: str | None = Header(None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError(
            code="INVALID_EXTERNAL_TOKEN",
            message="缺少 Authorization Header 或 Token 格式错误",
            status_code=401,
        )

    raw_token = authorization.removeprefix("Bearer ").strip()
    token, _user, _role, effective_scopes = ExternalAgentTokenService.authenticate_token(
        db, raw_token
    )

    return CandidateSubmissionService.get_candidate_submission(
        db=db,
        token_project_id=token.project_id,
        effective_scopes=effective_scopes,
        submission_id=submissionId,
    )


@router.post("/attachments/register", summary="外接 Agent Client 注册过程生成依赖附件")
async def register_candidate_attachment(
    body: RegisterAttachmentRequest,
    authorization: str | None = Header(None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError(
            code="INVALID_EXTERNAL_TOKEN",
            message="缺少 Authorization Header 或 Token 格式错误",
            status_code=401,
        )

    raw_token = authorization.removeprefix("Bearer ").strip()
    token, user, _role, effective_scopes = ExternalAgentTokenService.authenticate_token(
        db, raw_token
    )

    result = CandidateSubmissionService.register_candidate_attachment(
        db=db,
        token_project_id=token.project_id,
        user_id=user.id,
        effective_scopes=effective_scopes,
        submission_id=body.submissionId,
        file_name=body.fileName,
        file_size=body.fileSize,
        mime_type=body.mimeType,
        checksum=body.checksum,
    )
    return result


class SyncDraftRequest(BaseModel):
    capabilityId: uuid.UUID
    versionName: str
    filesSnapshot: dict[str, Any]


@router.post("/capabilities/sync-draft", summary="外接 Agent Client 同步能力开发草稿到平台")
async def sync_capability_draft(
    body: SyncDraftRequest,
    authorization: str | None = Header(None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError(
            code="INVALID_EXTERNAL_TOKEN",
            message="缺少 Authorization Header 或 Token 格式错误",
            status_code=401,
        )

    raw_token = authorization.removeprefix("Bearer ").strip()
    token, user, _role, effective_scopes = ExternalAgentTokenService.authenticate_token(
        db, raw_token
    )

    result = DraftSyncService.sync_capability_draft(
        db=db,
        token_project_id=token.project_id,
        user_id=user.id,
        effective_scopes=effective_scopes,
        capability_id=body.capabilityId,
        version_name=body.versionName,
        files_snapshot=body.filesSnapshot,
    )
    return result


@router.get("/project", summary="外接 Agent 获取当前 Token 归属项目的信息")
async def get_external_project_info(
    authorization: str | None = Header(None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError(
            code="INVALID_EXTERNAL_TOKEN",
            message="缺少 Authorization Header 或 Token 格式错误",
            status_code=401,
        )

    raw_token = authorization.removeprefix("Bearer ").strip()
    token, _user, role, _scopes = ExternalAgentTokenService.authenticate_token(db, raw_token)

    from testweave.db.models import Project

    project = db.get(Project, token.project_id)
    if not project:
        raise AppError(code="PROJECT_NOT_FOUND", message="项目不存在", status_code=404)

    return {
        "id": str(project.id),
        "name": project.name,
        "key": project.key,
        "roleInProject": role,
    }


def extract_attachment_text(storage_key: str) -> str | None:
    """自动从本地存储的附件中提取文本正文 (支持 .docx, .txt, .md 等)"""
    from testweave.modules.attachments.text_extractor import extract_attachment_text as extract

    return extract(storage_key)


def _build_requirement_dto(db: Session, r: Requirement) -> dict[str, Any]:
    from sqlalchemy import select

    from testweave.db.models import RequirementAttachment

    att_stmt = select(RequirementAttachment).where(
        RequirementAttachment.requirement_id == r.id,
        RequirementAttachment.status == "ACTIVE",
    )
    atts = db.scalars(att_stmt).all()

    att_list = [
        {
            "id": str(a.id),
            "filename": a.original_filename,
            "contentType": a.content_type,
            "sizeBytes": a.size_bytes,
            "description": a.description,
            "downloadUrl": f"/external/v1/requirements/{r.id}/attachments/{a.id}/download",
        }
        for a in atts
    ]

    content_doc = (r.description or "").strip()
    extracted_texts = []

    for a in atts:
        extracted = extract_attachment_text(a.storage_key)
        if extracted:
            extracted_texts.append(
                f"--- 需求附件文件 [{a.original_filename}] 提取正文内容 ---:\n{extracted}"
            )

    if extracted_texts:
        combined_attachment_text = "\n\n".join(extracted_texts)
        if not content_doc:
            content_doc = combined_attachment_text
        else:
            content_doc += f"\n\n{combined_attachment_text}"
    elif atts:
        att_descs = "\n".join(
            [f"- 文件名: {a.original_filename} (说明: {a.description or '暂无说明'})" for a in atts]
        )
        if not content_doc:
            content_doc = f"需求【{r.title}】包含关联需求文档附件：\n{att_descs}"
        else:
            content_doc += f"\n\n关联需求文档附件：\n{att_descs}"

    if not content_doc:
        content_doc = f"需求【{r.title}】暂未录入额外详细文字正文。"

    return {
        "id": str(r.id),
        "key": r.requirement_no,
        "title": r.title,
        "status": r.status,
        "priority": r.priority,
        "description": content_doc,
        "contentDoc": content_doc,
        "acceptanceCriteria": r.acceptance_criteria,
        "attachments": att_list,
        "createdAt": r.created_at.isoformat() if r.created_at else None,
    }


def _get_task_requirements(db: Session, task_id: uuid.UUID) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from testweave.db.models import Requirement, TestTaskRequirement

    stmt = (
        select(Requirement)
        .join(TestTaskRequirement, TestTaskRequirement.requirement_id == Requirement.id)
        .where(TestTaskRequirement.task_id == task_id)
    )
    reqs = db.scalars(stmt).all()
    return [_build_requirement_dto(db, r) for r in reqs]


@router.get("/tasks", summary="外接 Agent 获取当前项目包含的测试任务列表")
async def get_external_project_tasks(
    authorization: str | None = Header(None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError(
            code="INVALID_EXTERNAL_TOKEN",
            message="缺少 Authorization Header 或 Token 格式错误",
            status_code=401,
        )

    raw_token = authorization.removeprefix("Bearer ").strip()
    token, _user, _role, effective_scopes = ExternalAgentTokenService.authenticate_token(
        db, raw_token
    )
    ExternalAgentTokenService.verify_scope(effective_scopes, READ_SCOPES)

    from sqlalchemy import select

    from testweave.db.models import TestTask

    stmt = (
        select(TestTask)
        .where(TestTask.project_id == token.project_id)
        .order_by(TestTask.created_at.desc())
    )
    tasks = db.scalars(stmt).all()

    res_tasks = []
    for t in tasks:
        reqs = _get_task_requirements(db, t.id)
        first_req = reqs[0] if reqs else None
        res_tasks.append(
            {
                "id": str(t.id),
                "key": t.task_no,
                "name": t.title,
                "status": t.status,
                "taskType": t.task_type,
                "priority": t.priority,
                "description": t.description,
                "createdAt": t.created_at.isoformat() if t.created_at else None,
                "requirementId": first_req["id"] if first_req else None,
                "requirementKey": first_req["key"] if first_req else None,
                "requirementTitle": first_req["title"] if first_req else None,
                "requirements": reqs,
            }
        )

    return {
        "projectId": str(token.project_id),
        "tasks": res_tasks,
    }


@router.get("/tasks/{taskId}", summary="外接 Agent 获取指定测试任务的详情与关联需求")
async def get_external_task_detail(
    taskId: uuid.UUID,
    authorization: str | None = Header(None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError(
            code="INVALID_EXTERNAL_TOKEN",
            message="缺少 Authorization Header 或 Token 格式错误",
            status_code=401,
        )

    raw_token = authorization.removeprefix("Bearer ").strip()
    token, _user, _role, effective_scopes = ExternalAgentTokenService.authenticate_token(
        db, raw_token
    )
    ExternalAgentTokenService.verify_scope(effective_scopes, READ_SCOPES)

    from testweave.db.models import TestTask

    task = db.get(TestTask, taskId)
    if not task or task.project_id != token.project_id:
        raise AppError(
            code="TASK_NOT_FOUND", message=f"未找到 ID 为 {taskId} 的测试任务", status_code=404
        )

    reqs = _get_task_requirements(db, task.id)
    first_req = reqs[0] if reqs else None

    return {
        "id": str(task.id),
        "key": task.task_no,
        "name": task.title,
        "status": task.status,
        "taskType": task.task_type,
        "priority": task.priority,
        "description": task.description,
        "createdAt": task.created_at.isoformat() if task.created_at else None,
        "requirementId": first_req["id"] if first_req else None,
        "requirementKey": first_req["key"] if first_req else None,
        "requirementTitle": first_req["title"] if first_req else None,
        "requirements": reqs,
    }


@router.get("/tasks/{taskId}/requirements", summary="获取测试任务关联的需求列表")
@router.get("/tasks/{taskId}/requirement", summary="获取测试任务关联的需求详情")
async def get_external_task_requirements_endpoint(
    taskId: uuid.UUID,
    authorization: str | None = Header(None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError(
            code="INVALID_EXTERNAL_TOKEN",
            message="缺少 Authorization Header 或 Token 格式错误",
            status_code=401,
        )

    raw_token = authorization.removeprefix("Bearer ").strip()
    token, _user, _role, effective_scopes = ExternalAgentTokenService.authenticate_token(
        db, raw_token
    )
    ExternalAgentTokenService.verify_scope(effective_scopes, READ_SCOPES)

    from testweave.db.models import TestTask

    task = db.get(TestTask, taskId)
    if not task or task.project_id != token.project_id:
        raise AppError(
            code="TASK_NOT_FOUND", message=f"未找到 ID 为 {taskId} 的测试任务", status_code=404
        )

    reqs = _get_task_requirements(db, task.id)
    return {
        "taskId": str(task.id),
        "taskKey": task.task_no,
        "requirements": reqs,
    }


@router.get("/requirements", summary="获取项目需求列表")
async def get_external_project_requirements(
    authorization: str | None = Header(None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError(
            code="INVALID_EXTERNAL_TOKEN",
            message="缺少 Authorization Header 或 Token 格式错误",
            status_code=401,
        )

    raw_token = authorization.removeprefix("Bearer ").strip()
    token, _user, _role, effective_scopes = ExternalAgentTokenService.authenticate_token(
        db, raw_token
    )
    ExternalAgentTokenService.verify_scope(effective_scopes, READ_SCOPES)

    from sqlalchemy import select

    from testweave.db.models import Requirement

    stmt = (
        select(Requirement)
        .where(Requirement.project_id == token.project_id)
        .order_by(Requirement.created_at.desc())
    )
    reqs = db.scalars(stmt).all()

    return {
        "projectId": str(token.project_id),
        "requirements": [_build_requirement_dto(db, r) for r in reqs],
    }


@router.get("/requirements/{requirementId}", summary="获取特定需求详情及正文内容")
async def get_external_requirement_detail(
    requirementId: uuid.UUID,
    authorization: str | None = Header(None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError(
            code="INVALID_EXTERNAL_TOKEN",
            message="缺少 Authorization Header 或 Token 格式错误",
            status_code=401,
        )

    raw_token = authorization.removeprefix("Bearer ").strip()
    token, _user, _role, effective_scopes = ExternalAgentTokenService.authenticate_token(
        db, raw_token
    )
    ExternalAgentTokenService.verify_scope(effective_scopes, READ_SCOPES)

    from testweave.db.models import Requirement

    req = db.get(Requirement, requirementId)
    if not req or req.project_id != token.project_id:
        raise AppError(
            code="REQUIREMENT_NOT_FOUND",
            message=f"未找到 ID 为 {requirementId} 的需求",
            status_code=404,
        )

    return _build_requirement_dto(db, req)


@router.get(
    "/requirements/{requirementId}/attachments/{attachmentId}/download",
    summary="外接 Agent 下载需求关联附件原文",
)
async def download_external_requirement_attachment(
    requirementId: uuid.UUID,
    attachmentId: uuid.UUID,
    authorization: str | None = Header(None, alias="Authorization"),
    db: Session = Depends(get_db),
):
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError(
            code="INVALID_EXTERNAL_TOKEN",
            message="缺少 Authorization Header 或 Token 格式错误",
            status_code=401,
        )

    raw_token = authorization.removeprefix("Bearer ").strip()
    token, _user, _role, effective_scopes = ExternalAgentTokenService.authenticate_token(
        db, raw_token
    )
    ExternalAgentTokenService.verify_scope(effective_scopes, READ_SCOPES)

    from urllib.parse import quote

    from fastapi.responses import StreamingResponse

    from testweave.core.config import get_settings
    from testweave.db.models import RequirementAttachment
    from testweave.infrastructure.storage import LocalStorageProvider

    att = db.get(RequirementAttachment, attachmentId)
    if not att or att.requirement_id != requirementId or att.project_id != token.project_id:
        raise AppError(
            code="ATTACHMENT_NOT_FOUND", message="附件不存在或无权限访问", status_code=404
        )

    storage = LocalStorageProvider(get_settings().storage_local_dir)
    stream = await storage.get(att.storage_key)

    filename_encoded = quote(att.original_filename)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{filename_encoded}"}
    return StreamingResponse(stream, media_type=att.content_type, headers=headers)
