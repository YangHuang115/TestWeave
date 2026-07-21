import gzip
import os
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Path, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.api.dependencies.auth import get_current_user
from testweave.api.dependencies.database import get_db
from testweave.api.dependencies.projects import require_project_permission
from testweave.core.errors import AppError
from testweave.db.models import (
    CodeRepository,
    GitCommit,
    GitCommitFile,
    RequirementCommitLink,
    User,
)
from testweave.modules.audit.service import AuditService
from testweave.modules.repositories.matcher import MatcherService
from testweave.modules.repositories.schemas import (
    RepositoryCreateOrUpdateRequest,
    RepositoryResponse,
    RepositoryVerifyRequest,
)
from testweave.modules.repositories.service import RepositoryService
from testweave.modules.repositories.sync import RepositorySyncManager
from testweave.shared.permissions import VERSION_MANAGE, VERSION_READ

router = APIRouter()


@router.get(
    "/projects/{projectId}/repository",
    response_model=RepositoryResponse,
    dependencies=[Depends(require_project_permission(VERSION_READ))],
)
def get_repository_config(
    projectId: UUID = Path(...),
    db: Session = Depends(get_db),
):
    repo = RepositoryService.get_repository_by_project_id(db, str(projectId))
    if not repo:
        raise AppError(
            code="REPOSITORY_NOT_FOUND",
            message="该项目尚未配置代码仓库",
            status_code=404,
        )

    res = RepositoryResponse.model_validate(repo)
    res.has_credential = bool(repo.credential_ref)
    return res


@router.post(
    "/projects/{projectId}/repository",
    response_model=RepositoryResponse,
    dependencies=[Depends(require_project_permission(VERSION_MANAGE))],
)
def create_or_update_repository_config(
    projectId: UUID = Path(...),
    payload: RepositoryCreateOrUpdateRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    request_id: str = Query(""),
):
    repo = RepositoryService.create_or_update_repository(
        db,
        project_id=str(projectId),
        name=payload.name,
        remote_url=payload.remote_url,
        auth_type=payload.auth_type,
        credential_content=payload.credential_content,
        main_branch=payload.main_branch,
        enabled=payload.enabled,
        row_version=payload.row_version,
        actor_id=str(current_user.id),
        request_id=request_id,
    )
    db.commit()

    res = RepositoryResponse.model_validate(repo)
    res.has_credential = bool(repo.credential_ref)
    return res


@router.post(
    "/projects/{projectId}/repository/verify",
    dependencies=[Depends(require_project_permission(VERSION_MANAGE))],
)
def verify_repository_connection(
    projectId: UUID = Path(...),
    payload: RepositoryVerifyRequest = Body(...),
    db: Session = Depends(get_db),
):
    test_cred = payload.credential_content
    if test_cred is None:
        existing = RepositoryService.get_repository_by_project_id(db, str(projectId))
        if existing and existing.credential_ref and existing.remote_url == payload.remote_url:
            from testweave.shared.crypto import CryptoService

            test_cred = CryptoService.decrypt(existing.credential_ref)

    RepositoryService.verify_connection(
        remote_url=payload.remote_url,
        auth_type=payload.auth_type,
        credential_content=test_cred,
        main_branch=payload.main_branch,
    )
    return JSONResponse(
        content={"status": "success", "message": "连接验证成功，远程仓库及主干分支有效"}
    )


@router.post(
    "/projects/{projectId}/repository/sync",
    dependencies=[Depends(require_project_permission(VERSION_MANAGE))],
)
def trigger_repository_sync(
    projectId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = RepositoryService.get_repository_by_project_id(db, str(projectId))
    if not repo:
        raise AppError(
            code="REPOSITORY_NOT_FOUND",
            message="该项目尚未配置代码仓库",
            status_code=404,
        )

    job = RepositorySyncManager.create_sync_job(
        db,
        str(projectId),
        str(repo.id),
        str(current_user.id),
    )
    db.commit()

    # 临时在请求线程中触发 poll。后台多 Worker 可由独立 worker 轮询；
    # 为便于前端演示及单机响应，API 后端也手动触发一次 Worker 调度。
    RepositorySyncManager.poll_and_execute_jobs(db, f"api-trigger-{current_user.username}")

    return {
        "job_id": str(job.id),
        "status": job.status,
        "attempt": job.attempt,
    }


@router.get(
    "/projects/{projectId}/repository/sync/jobs/{jobId}",
    dependencies=[Depends(require_project_permission(VERSION_READ))],
)
def get_sync_job_status(
    projectId: UUID = Path(...),
    jobId: UUID = Path(...),
    db: Session = Depends(get_db),
):
    job = RepositorySyncManager.get_sync_job(db, str(jobId))
    if not job or job.project_id != projectId:
        raise AppError(code="SYNC_JOB_NOT_FOUND", message="未找到对应的同步任务", status_code=404)

    return {
        "id": str(job.id),
        "status": job.status,
        "attempt": job.attempt,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error_code": job.error_code,
        "error_message": job.error_message,
    }


@router.post(
    "/projects/{projectId}/repository/rematch",
    dependencies=[Depends(require_project_permission(VERSION_MANAGE))],
)
def trigger_rematch(
    projectId: UUID = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    request_id: str = Query(""),
):
    repo = RepositoryService.get_repository_by_project_id(db, str(projectId))
    if not repo:
        raise AppError(
            code="REPOSITORY_NOT_FOUND",
            message="该项目尚未配置代码仓库",
            status_code=404,
        )

    links_created = MatcherService.rematch_project_requirements(db, str(projectId))
    db.commit()

    AuditService.log_event(
        db,
        action="repository.rematch",
        object_type="CodeRepository",
        object_id=str(repo.id),
        summary=f"手动触发了仓库代码与需求关联关系重新匹配，重建了 {links_created} 个绑定链接",
        request_id=request_id,
        project_id=projectId,
        actor_id=current_user.id,
    )

    return {
        "status": "success",
        "links_rebuilt": links_created,
    }


# === 阶段 8 差异浏览器获取与特定需求关联的 Commit 列表 ===
@router.get(
    "/projects/{projectId}/requirements/{requirementId}/commits",
    dependencies=[Depends(require_project_permission(VERSION_READ))],
)
def get_requirement_commits(
    projectId: UUID = Path(...),
    requirementId: UUID = Path(...),
    db: Session = Depends(get_db),
):
    stmt = (
        select(GitCommit)
        .join(RequirementCommitLink, RequirementCommitLink.commit_id == GitCommit.id)
        .where(
            RequirementCommitLink.project_id == projectId,
            RequirementCommitLink.requirement_id == requirementId,
            RequirementCommitLink.status == "ACTIVE",
        )
        .order_by(GitCommit.committed_at.desc())
    )
    commits = db.scalars(stmt).all()
    return [
        {
            "id": str(c.id),
            "sha": c.sha,
            "author_name": c.author_name,
            "committer_name": c.committer_name,
            "committed_at": c.committed_at.isoformat(),
            "message": c.message,
            "files_changed": c.files_changed,
            "additions": c.additions,
            "deletions": c.deletions,
        }
        for c in commits
    ]


@router.get(
    "/projects/{projectId}/commits/{commitId}/files",
    dependencies=[Depends(require_project_permission(VERSION_READ))],
)
def get_commit_files(
    projectId: UUID = Path(...),
    commitId: UUID = Path(...),
    db: Session = Depends(get_db),
):
    # 验证 commit 是否属于该项目下的仓库
    stmt_commit = (
        select(GitCommit)
        .join(CodeRepository, CodeRepository.id == GitCommit.repository_id)
        .where(GitCommit.id == commitId, CodeRepository.project_id == projectId)
    )
    commit = db.scalar(stmt_commit)
    if not commit:
        raise AppError(code="COMMIT_NOT_FOUND", message="未找到对应的提交记录", status_code=404)

    stmt_files = select(GitCommitFile).where(GitCommitFile.commit_id == commitId)
    files = db.scalars(stmt_files).all()

    return [
        {
            "id": str(f.id),
            "old_path": f.old_path,
            "new_path": f.new_path,
            "change_type": f.change_type,
            "is_binary": f.is_binary,
            "additions": f.additions,
            "deletions": f.deletions,
            "patch_size_bytes": f.patch_size_bytes,
            "patch_truncated": f.patch_truncated,
        }
        for f in files
    ]


@router.get(
    "/projects/{projectId}/commits/{commitId}/files/{fileId}/patch",
    dependencies=[Depends(require_project_permission(VERSION_READ))],
)
def get_file_patch_content(
    projectId: UUID = Path(...),
    commitId: UUID = Path(...),
    fileId: UUID = Path(...),
    db: Session = Depends(get_db),
):
    stmt_file = (
        select(GitCommitFile)
        .join(GitCommit, GitCommit.id == GitCommitFile.commit_id)
        .join(CodeRepository, CodeRepository.id == GitCommit.repository_id)
        .where(
            GitCommitFile.id == fileId,
            GitCommitFile.commit_id == commitId,
            CodeRepository.project_id == projectId,
        )
    )
    file_record = db.scalar(stmt_file)
    if not file_record:
        raise AppError(code="FILE_NOT_FOUND", message="未找到对应的文件记录", status_code=404)

    if not file_record.patch_storage_key:
        return {"patch": "", "truncated": False}

    # 获取稳定的 data 目录绝对路径
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
    data_dir = os.path.join(base_dir, "data")
    if not os.path.exists(data_dir):
        data_dir = os.path.join(os.getcwd(), "data")

    patch_path = os.path.join(data_dir, file_record.patch_storage_key)
    if not os.path.exists(patch_path):
        raise AppError(
            code="PATCH_NOT_FOUND",
            message="未找到该文件的差异 Diff 详情",
            status_code=404,
        )

    # gzip 解压为文本
    with gzip.open(patch_path, "rt", encoding="utf-8") as f:
        content = f.read()

    return {
        "patch": content,
        "truncated": file_record.patch_truncated,
    }
