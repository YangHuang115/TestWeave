import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import RequirementCommitLink, VersionRequirement
from testweave.modules.projects.service import ProjectService
from testweave.modules.requirements.service import RequirementService, normalize_requirement_no
from testweave.modules.users.service import UserService
from testweave.modules.versions.service import VersionService


@pytest.fixture
def req_test_context(db: Session) -> dict:
    user = UserService.create_user(
        db,
        username="reqtester",
        email="req@testweave.com",
        display_name="Req Tester",
        password="pwd",
    )
    db.commit()

    project = ProjectService.create_project(
        db,
        key="REQPROJ",
        name="Req Project",
        owner_id=user.id,
        request_id="req-p",
    )
    db.commit()

    version = VersionService.create_version(
        db,
        project_id=project.id,
        key="v1.0",
        name="Version 1.0",
        owner_id=user.id,
        actor_id=user.id,
        request_id="req-v",
    )
    db.commit()

    return {"user": user, "project": project, "version": version}


def test_normalize_requirement_no() -> None:
    assert normalize_requirement_no("  Req-1001 ") == "req-1001"
    # NFKC 规范化 (例如全角字符)
    assert normalize_requirement_no("ＲＥＱ－１００１") == "req-1001"


def test_create_requirement_success(db: Session, req_test_context: dict) -> None:
    user = req_test_context["user"]
    project = req_test_context["project"]

    req = RequirementService.create_requirement(
        db,
        project_id=project.id,
        requirement_no=" REQ-1001 ",
        title="  支付宝支付接口支持 ",
        description="支持支付宝扫码与沙箱环境",
        priority="HIGH",
        owner_id=user.id,
        actor_id=user.id,
        request_id="req-c1",
    )
    db.commit()

    assert req.id is not None
    assert req.requirement_no == "REQ-1001"
    assert req.requirement_no_normalized == "req-1001"
    assert req.title == "支付宝支付接口支持"
    assert req.priority == "HIGH"
    assert req.status == "DRAFT"
    assert req.owner_id == user.id
    assert req.row_version == 1


def test_create_requirement_key_conflict(db: Session, req_test_context: dict) -> None:
    user = req_test_context["user"]
    project = req_test_context["project"]

    RequirementService.create_requirement(
        db,
        project_id=project.id,
        requirement_no="REQ-1001",
        title="Req 1",
        description=None,
        priority="MEDIUM",
        owner_id=user.id,
        actor_id=user.id,
        request_id="req-c1",
    )
    db.commit()

    # 重复创建相同规范化单号的需求，抛出 400 REQUIREMENT_KEY_CONFLICT
    with pytest.raises(AppError) as exc_info:
        RequirementService.create_requirement(
            db,
            project_id=project.id,
            requirement_no=" req-1001 ",
            title="Req 2",
            description=None,
            priority="MEDIUM",
            owner_id=user.id,
            actor_id=user.id,
            request_id="req-c2",
        )
    assert exc_info.value.code == "REQUIREMENT_KEY_CONFLICT"


def test_update_requirement_success_and_optimistic_lock(
    db: Session, req_test_context: dict
) -> None:
    user = req_test_context["user"]
    project = req_test_context["project"]

    req = RequirementService.create_requirement(
        db,
        project_id=project.id,
        requirement_no="REQ-1001",
        title="Old Title",
        description="Old Desc",
        priority="LOW",
        owner_id=user.id,
        actor_id=user.id,
        request_id="req-c1",
    )
    db.commit()

    # 1. 成功更新
    updated = RequirementService.update_requirement(
        db,
        project_id=project.id,
        requirement_id=req.id,
        requirement_no="REQ-1001",
        title="New Title",
        description="New Desc",
        priority="HIGH",
        owner_id=user.id,
        status="READY",
        expected_row_version=1,
        actor_id=user.id,
        request_id="req-u1",
    )
    db.commit()

    assert updated.title == "New Title"
    assert updated.description == "New Desc"
    assert updated.priority == "HIGH"
    assert updated.status == "READY"
    assert updated.row_version == 2

    # 2. 乐观锁并发冲突校验
    with pytest.raises(AppError) as exc_info:
        RequirementService.update_requirement(
            db,
            project_id=project.id,
            requirement_id=req.id,
            requirement_no="REQ-1001",
            title="Concurrent Title",
            description="Concurrent Desc",
            priority="HIGH",
            owner_id=user.id,
            status="READY",
            expected_row_version=1,  # 错误的 expected_row_version
            actor_id=user.id,
            request_id="req-u2",
        )
    assert exc_info.value.code == "OPTIMISTIC_LOCK_CONFLICT"


def test_update_requirement_no_change_with_commits(db: Session, req_test_context: dict) -> None:
    user = req_test_context["user"]
    project = req_test_context["project"]

    req = RequirementService.create_requirement(
        db,
        project_id=project.id,
        requirement_no="REQ-1001",
        title="Old Title",
        description=None,
        priority="LOW",
        owner_id=user.id,
        actor_id=user.id,
        request_id="req-c1",
    )
    db.commit()

    # 模拟代码提交关联记录
    commit_link = RequirementCommitLink(
        project_id=project.id,
        requirement_id=req.id,
        commit_id=uuid.uuid4(),
        matched_requirement_no="REQ-1001",
    )
    db.add(commit_link)
    db.commit()

    # 1. 如果有提交关联，但未修改需求单号，可正常更新
    updated = RequirementService.update_requirement(
        db,
        project_id=project.id,
        requirement_id=req.id,
        requirement_no="REQ-1001",
        title="New Title",
        description=None,
        priority="LOW",
        owner_id=user.id,
        status="DRAFT",
        expected_row_version=1,
        actor_id=user.id,
        request_id="req-u1",
    )
    db.commit()
    assert updated.title == "New Title"

    # 2. 修改了需求单号，且未传 force_change_no=True，则抛出 REQUIREMENT_HAS_COMMITS 报错
    with pytest.raises(AppError) as exc_info:
        RequirementService.update_requirement(
            db,
            project_id=project.id,
            requirement_id=req.id,
            requirement_no="REQ-1002",
            title="New Title",
            description=None,
            priority="LOW",
            owner_id=user.id,
            status="DRAFT",
            expected_row_version=2,
            actor_id=user.id,
            request_id="req-u2",
            force_change_no=False,
        )
    assert exc_info.value.code == "REQUIREMENT_HAS_COMMITS"

    # 3. 传入 force_change_no=True，强制修改成功，且已有的 commit 关联记录被清空
    forced = RequirementService.update_requirement(
        db,
        project_id=project.id,
        requirement_id=req.id,
        requirement_no="REQ-1002",
        title="New Title",
        description=None,
        priority="LOW",
        owner_id=user.id,
        status="DRAFT",
        expected_row_version=2,
        actor_id=user.id,
        request_id="req-u3",
        force_change_no=True,
    )
    db.commit()
    assert forced.requirement_no == "REQ-1002"
    # 验证关联已删除
    assert (
        db.scalar(
            select(RequirementCommitLink).where(RequirementCommitLink.requirement_id == req.id)
        )
        is None
    )


def test_associate_and_dissociate_version(db: Session, req_test_context: dict) -> None:
    user = req_test_context["user"]
    project = req_test_context["project"]
    version = req_test_context["version"]

    req = RequirementService.create_requirement(
        db,
        project_id=project.id,
        requirement_no="REQ-1001",
        title="Title",
        description=None,
        priority="LOW",
        owner_id=user.id,
        actor_id=user.id,
        request_id="req-c1",
    )
    db.commit()

    # 1. 成功关联
    RequirementService.associate_to_version(
        db,
        project_id=project.id,
        requirement_id=req.id,
        version_id=version.id,
        actor_id=user.id,
        request_id="req-a1",
    )
    db.commit()

    link = db.scalar(
        select(VersionRequirement).where(
            VersionRequirement.version_id == version.id, VersionRequirement.requirement_id == req.id
        )
    )
    assert link is not None

    # 2. 版本已归档时，无法修改或解绑需求关联
    VersionService.archive_version(
        db,
        project_id=project.id,
        version_id=version.id,
        actor_id=user.id,
        request_id="req-arch",
    )
    db.commit()

    with pytest.raises(AppError) as exc_info:
        RequirementService.dissociate_from_version(
            db,
            project_id=project.id,
            requirement_id=req.id,
            version_id=version.id,
            actor_id=user.id,
            request_id="req-d1",
        )
    assert exc_info.value.code == "VERSION_ARCHIVED"


def test_create_requirement_auto_no(db: Session, req_test_context: dict) -> None:
    user = req_test_context["user"]
    project = req_test_context["project"]

    # 1. 没有任何需求时，生成第一个 REQ-10001
    req1 = RequirementService.create_requirement(
        db,
        project_id=project.id,
        requirement_no=None,
        title="Auto Req 1",
        description=None,
        priority="LOW",
        owner_id=user.id,
        actor_id=user.id,
        request_id="req-a1",
    )
    db.commit()
    assert req1.requirement_no == "REQ-10001"

    # 2. 存在 REQ-10001 时，自动生成下一个 REQ-10002
    req2 = RequirementService.create_requirement(
        db,
        project_id=project.id,
        requirement_no="",
        title="Auto Req 2",
        description=None,
        priority="MEDIUM",
        owner_id=user.id,
        actor_id=user.id,
        request_id="req-a2",
    )
    db.commit()
    assert req2.requirement_no == "REQ-10002"
