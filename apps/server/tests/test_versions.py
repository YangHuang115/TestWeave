from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.modules.projects.service import ProjectService
from testweave.modules.users.service import UserService
from testweave.modules.versions.service import VersionService


@pytest.fixture
def test_context(db: Session) -> dict:
    """初始化测试项目与成员"""
    user = UserService.create_user(
        db,
        username="versiontester",
        email="vt@testweave.com",
        display_name="Version Tester",
        password="test-password",
    )
    db.commit()

    project = ProjectService.create_project(
        db,
        key="VTPROJ",
        name="Version Test Project",
        owner_id=user.id,
        request_id="req-p1",
    )
    db.commit()

    return {"user": user, "project": project}


def test_create_version_success(db: Session, test_context: dict) -> None:
    user = test_context["user"]
    project = test_context["project"]

    now = datetime.now(UTC)
    planned_start = now + timedelta(days=1)
    planned_end = now + timedelta(days=10)

    version = VersionService.create_version(
        db,
        project_id=project.id,
        key="v1.0.0",
        name="V1.0.0 Release",
        description="First major release",
        owner_id=user.id,
        planned_start_at=planned_start,
        planned_end_at=planned_end,
        actor_id=user.id,
        request_id="req-v1",
    )
    db.commit()

    assert version.id is not None
    assert version.key == "v1.0.0"
    assert version.key_normalized == "v1.0.0"
    assert version.name == "V1.0.0 Release"
    assert version.status == "PLANNING"
    assert version.owner_id == user.id
    assert version.planned_start_at is not None
    assert version.planned_end_at is not None
    assert (
        abs(
            (
                version.planned_start_at.replace(tzinfo=None) - planned_start.replace(tzinfo=None)
            ).total_seconds()
        )
        < 1
    )
    assert (
        abs(
            (
                version.planned_end_at.replace(tzinfo=None) - planned_end.replace(tzinfo=None)
            ).total_seconds()
        )
        < 1
    )
    assert version.row_version == 1


def test_create_version_time_validation(db: Session, test_context: dict) -> None:
    user = test_context["user"]
    project = test_context["project"]

    now = datetime.now(UTC)
    # 结束时间早于开始时间
    planned_start = now + timedelta(days=10)
    planned_end = now + timedelta(days=1)

    with pytest.raises(AppError) as exc_info:
        VersionService.create_version(
            db,
            project_id=project.id,
            key="v1.0.0",
            name="V1.0.0 Release",
            owner_id=user.id,
            planned_start_at=planned_start,
            planned_end_at=planned_end,
            actor_id=user.id,
            request_id="req-v1",
        )
    assert exc_info.value.code == "VERSION_TIME_INVALID"


def test_create_version_key_conflict(db: Session, test_context: dict) -> None:
    user = test_context["user"]
    project = test_context["project"]

    # 1. 成功创建版本
    VersionService.create_version(
        db,
        project_id=project.id,
        key="v1.0.0",
        name="V1.0.0 Release",
        owner_id=user.id,
        actor_id=user.id,
        request_id="req-v1",
    )
    db.commit()

    # 2. 冲突校验 (忽略大小写及空格)
    with pytest.raises(AppError) as exc_info:
        VersionService.create_version(
            db,
            project_id=project.id,
            key=" V1.0.0 ",
            name="V1.0.0 Duplicate",
            owner_id=user.id,
            actor_id=user.id,
            request_id="req-v2",
        )
    assert exc_info.value.code == "VERSION_KEY_CONFLICT"


def test_update_version_success_and_optimistic_lock(db: Session, test_context: dict) -> None:
    user = test_context["user"]
    project = test_context["project"]

    version = VersionService.create_version(
        db,
        project_id=project.id,
        key="v1.0.0",
        name="V1.0.0 Release",
        owner_id=user.id,
        actor_id=user.id,
        request_id="req-v1",
    )
    db.commit()

    # 正常更新
    updated = VersionService.update_version(
        db,
        project_id=project.id,
        version_id=version.id,
        name="V1.0.0 Updated",
        description="New description",
        owner_id=user.id,
        status="ACTIVE",  # PLANNING -> ACTIVE
        planned_start_at=None,
        planned_end_at=None,
        actor_id=user.id,
        request_id="req-u1",
        expected_row_version=1,
    )
    db.commit()

    assert updated.name == "V1.0.0 Updated"
    assert updated.status == "ACTIVE"
    assert updated.row_version == 2

    # 乐观锁并发冲突校验 (旧的 expected_row_version = 1 应该抛出异常)
    with pytest.raises(AppError) as exc_info:
        VersionService.update_version(
            db,
            project_id=project.id,
            version_id=version.id,
            name="V1.0.0 Concurrent",
            description="Concurrent description",
            owner_id=user.id,
            status="ACTIVE",
            planned_start_at=None,
            planned_end_at=None,
            actor_id=user.id,
            request_id="req-u2",
            expected_row_version=1,
        )
    assert exc_info.value.code == "OPTIMISTIC_LOCK_CONFLICT"


def test_version_status_transitions(db: Session, test_context: dict) -> None:
    user = test_context["user"]
    project = test_context["project"]

    version = VersionService.create_version(
        db,
        project_id=project.id,
        key="v1.0.0",
        name="V1.0.0",
        owner_id=user.id,
        actor_id=user.id,
        request_id="req-v1",
    )
    db.commit()

    # PLANNING -> TESTING (非法流转，跳过了 ACTIVE)
    with pytest.raises(AppError) as exc_info:
        VersionService.update_version(
            db,
            project_id=project.id,
            version_id=version.id,
            name="V1.0.0",
            description=None,
            owner_id=user.id,
            status="TESTING",
            planned_start_at=None,
            planned_end_at=None,
            actor_id=user.id,
            request_id="req-u1",
            expected_row_version=1,
        )
    assert exc_info.value.code == "VERSION_STATUS_TRANSITION_INVALID"


def test_archive_and_restore_version(db: Session, test_context: dict) -> None:
    user = test_context["user"]
    project = test_context["project"]

    version = VersionService.create_version(
        db,
        project_id=project.id,
        key="v1.0.0",
        name="V1.0.0",
        owner_id=user.id,
        actor_id=user.id,
        request_id="req-v1",
    )
    # PLANNING -> ACTIVE
    VersionService.update_version(
        db,
        project_id=project.id,
        version_id=version.id,
        name="V1.0.0",
        description=None,
        owner_id=user.id,
        status="ACTIVE",
        planned_start_at=None,
        planned_end_at=None,
        actor_id=user.id,
        request_id="req-u1",
        expected_row_version=1,
    )
    db.commit()

    # 1. 归档版本
    archived = VersionService.archive_version(
        db,
        project_id=project.id,
        version_id=version.id,
        actor_id=user.id,
        request_id="req-a1",
    )
    db.commit()

    assert archived.status == "ARCHIVED"
    assert archived.previous_status == "ACTIVE"

    # 2. 归档版本为只读校验
    with pytest.raises(AppError) as exc_info:
        VersionService.update_version(
            db,
            project_id=project.id,
            version_id=version.id,
            name="V1.0.0 Modified",
            description=None,
            owner_id=user.id,
            status="ARCHIVED",
            planned_start_at=None,
            planned_end_at=None,
            actor_id=user.id,
            request_id="req-u2",
            expected_row_version=3,
        )
    assert exc_info.value.code == "VERSION_ARCHIVED"

    # 3. 恢复版本
    restored = VersionService.restore_version(
        db,
        project_id=project.id,
        version_id=version.id,
        actor_id=user.id,
        request_id="req-r1",
    )
    db.commit()

    assert restored.status == "ACTIVE"
    assert restored.previous_status is None
