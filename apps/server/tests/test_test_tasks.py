from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    TestTaskBlockage,
    TestTaskRequirement,
    TestTaskStatusHistory,
)
from testweave.modules.projects.service import ProjectService
from testweave.modules.requirements.service import RequirementService
from testweave.modules.test_tasks.service import TestTaskService
from testweave.modules.users.service import UserService
from testweave.modules.versions.service import VersionService


@pytest.fixture
def task_test_context(db: Session) -> dict:
    """初始化任务测试上下文：用户、项目、版本和需求"""
    user = UserService.create_user(
        db,
        username="tasktester",
        email="tt@testweave.com",
        display_name="Task Tester",
        password="test-password",
    )
    db.commit()

    project = ProjectService.create_project(
        db,
        key="TTPROJ",
        name="Task Test Project",
        owner_id=user.id,
        request_id="req-p1",
    )
    db.commit()

    # 1. 版本 - 包含起止时间
    now_time = datetime.now(UTC)
    version = VersionService.create_version(
        db,
        project_id=project.id,
        key="v1.0.0",
        name="V1.0.0 Release",
        owner_id=user.id,
        planned_start_at=now_time - timedelta(days=1),
        planned_end_at=now_time + timedelta(days=10),
        actor_id=user.id,
        request_id="req-v1",
    )
    db.commit()

    # 2. 版本 - 没有起止时间
    version_no_time = VersionService.create_version(
        db,
        project_id=project.id,
        key="v2.0.0",
        name="V2.0.0 Planning",
        owner_id=user.id,
        planned_start_at=None,
        planned_end_at=None,
        actor_id=user.id,
        request_id="req-v2",
    )
    db.commit()

    # 3. 需求
    req1 = RequirementService.create_requirement(
        db,
        project_id=project.id,
        requirement_no="REQ-001",
        title="短信发送功能",
        description="支持对接验证码发送",
        priority="HIGH",
        owner_id=user.id,
        actor_id=user.id,
        request_id="req-r1",
    )
    RequirementService.associate_to_version(
        db,
        project_id=project.id,
        requirement_id=req1.id,
        version_id=version.id,
        actor_id=user.id,
        request_id="req-r1-v1",
    )
    db.commit()

    return {
        "user": user,
        "project": project,
        "version": version,
        "version_no_time": version_no_time,
        "requirement": req1,
    }


def test_create_task_success(db: Session, task_test_context: dict) -> None:
    user = task_test_context["user"]
    project = task_test_context["project"]
    version = task_test_context["version"]
    req = task_test_context["requirement"]

    now_time = datetime.now(UTC)
    task = TestTaskService.create_task(
        db,
        project_id=project.id,
        version_id=version.id,
        task_type="CASE_DESIGN",
        title="支付用例设计",
        description="微信及支付宝通道设计",
        priority="HIGH",
        owner_id=user.id,
        planned_start_at=now_time,
        planned_end_at=now_time + timedelta(days=2),
        test_goal="覆盖支付全部成功与异常拦截路径",
        excluded_scope="不包括退款流程",
        tags_json=["支付", "用例设计"],
        actor_id=user.id,
        request_id="req-task-c1",
        requirement_id=req.id,
    )
    db.commit()

    assert task.id is not None
    assert task.task_no == "TASK-000001"
    assert task.status == "DRAFT"
    assert task.priority == "HIGH"
    assert task.row_version == 1

    # 验证状态历史是否已记录
    hist = db.scalar(select(TestTaskStatusHistory).where(TestTaskStatusHistory.task_id == task.id))
    assert hist is not None
    assert hist.from_status == "NONE"
    assert hist.to_status == "DRAFT"


def test_create_execution_task_rejected(db: Session, task_test_context: dict) -> None:
    user = task_test_context["user"]
    project = task_test_context["project"]
    version = task_test_context["version"]

    now_time = datetime.now(UTC)
    with pytest.raises(AppError) as exc_info:
        TestTaskService.create_task(
            db,
            project_id=project.id,
            version_id=version.id,
            task_type="TEST_EXECUTION",
            title="冒烟测试执行",
            description="",
            priority="MEDIUM",
            owner_id=user.id,
            planned_start_at=now_time,
            planned_end_at=now_time + timedelta(days=1),
            test_goal=None,
            excluded_scope=None,
            tags_json=None,
            actor_id=user.id,
            request_id="req-task-e1",
        )
    assert exc_info.value.code == "TEST_EXECUTION_MODULE_NOT_AVAILABLE"
    assert exc_info.value.status_code == 400


def test_create_task_time_validation(db: Session, task_test_context: dict) -> None:
    user = task_test_context["user"]
    project = task_test_context["project"]
    version = task_test_context["version"]
    req = task_test_context["requirement"]

    now_time = datetime.now(UTC)

    # 1. 结束时间早于开始时间
    with pytest.raises(AppError) as exc_info:
        TestTaskService.create_task(
            db,
            project_id=project.id,
            version_id=version.id,
            task_type="CASE_DESIGN",
            title="支付用例设计",
            description="",
            priority="HIGH",
            owner_id=user.id,
            planned_start_at=now_time + timedelta(days=2),
            planned_end_at=now_time + timedelta(days=1),
            test_goal=None,
            excluded_scope=None,
            tags_json=None,
            actor_id=user.id,
            request_id="req-t-err1",
            requirement_id=req.id,
        )
    assert exc_info.value.code == "TEST_TASK_DATE_INVALID"

    # 2. 结束时间超过版本时间上限 (版本截止是now + 10天，我们设为now + 11天)
    with pytest.raises(AppError) as exc_info:
        TestTaskService.create_task(
            db,
            project_id=project.id,
            version_id=version.id,
            task_type="CASE_DESIGN",
            title="支付用例设计",
            description="",
            priority="HIGH",
            owner_id=user.id,
            planned_start_at=now_time,
            planned_end_at=version.planned_end_at + timedelta(seconds=1),
            test_goal=None,
            excluded_scope=None,
            tags_json=None,
            actor_id=user.id,
            request_id="req-t-err2",
            requirement_id=req.id,
        )
    assert exc_info.value.code == "TEST_TASK_END_AFTER_VERSION_END"


def test_create_task_version_no_time_success(db: Session, task_test_context: dict) -> None:
    user = task_test_context["user"]
    project = task_test_context["project"]
    version_no_time = task_test_context["version_no_time"]
    req = task_test_context["requirement"]

    now_time = datetime.now(UTC)
    # 当版本没有截止时间时，应该允许创建任务且不报错
    task = TestTaskService.create_task(
        db,
        project_id=project.id,
        version_id=version_no_time.id,
        task_type="CASE_DESIGN",
        title="无截止时间版本任务",
        description="",
        priority="LOW",
        owner_id=user.id,
        planned_start_at=now_time,
        planned_end_at=now_time + timedelta(days=100),  # 很大也没事
        test_goal=None,
        excluded_scope=None,
        tags_json=None,
        actor_id=user.id,
        request_id="req-task-no-time",
        requirement_id=req.id,
    )
    db.commit()

    assert task.id is not None
    assert task.status == "DRAFT"


def test_update_task_and_optimistic_lock(db: Session, task_test_context: dict) -> None:
    user = task_test_context["user"]
    project = task_test_context["project"]
    version = task_test_context["version"]
    req = task_test_context["requirement"]

    now_time = datetime.now(UTC)
    task = TestTaskService.create_task(
        db,
        project_id=project.id,
        version_id=version.id,
        task_type="CASE_DESIGN",
        title="原标题",
        description="",
        priority="MEDIUM",
        owner_id=user.id,
        planned_start_at=now_time,
        planned_end_at=now_time + timedelta(days=2),
        test_goal=None,
        excluded_scope=None,
        tags_json=None,
        actor_id=user.id,
        request_id="req-task-lock",
        requirement_id=req.id,
    )
    db.commit()

    # 1. 乐观锁冲突校验
    with pytest.raises(AppError) as exc_info:
        TestTaskService.update_task(
            db,
            project_id=project.id,
            task_id=task.id,
            title="新标题",
            description="",
            priority="MEDIUM",
            owner_id=user.id,
            planned_start_at=task.planned_start_at,
            planned_end_at=task.planned_end_at,
            test_goal=None,
            excluded_scope=None,
            tags_json=None,
            expected_row_version=999,  # 错误的row_version
            actor_id=user.id,
            request_id="req-task-lock-err",
        )
    assert exc_info.value.code == "OPTIMISTIC_LOCK_CONFLICT"

    # 2. 正常更新
    updated_task = TestTaskService.update_task(
        db,
        project_id=project.id,
        task_id=task.id,
        title="新标题",
        description="更新后的描述",
        priority="MEDIUM",
        owner_id=user.id,
        planned_start_at=task.planned_start_at,
        planned_end_at=task.planned_end_at,
        test_goal="更新后的测试目标",
        excluded_scope="更新后的排除范围",
        tags_json=["新标签"],
        expected_row_version=task.row_version,
        actor_id=user.id,
        request_id="req-task-lock-ok",
    )
    db.commit()

    assert updated_task.title == "新标题"
    assert updated_task.description == "更新后的描述"
    assert updated_task.row_version == 2


def test_requirements_association_and_warning(db: Session, task_test_context: dict) -> None:
    user = task_test_context["user"]
    project = task_test_context["project"]
    version = task_test_context["version"]
    req = task_test_context["requirement"]

    # 创建第二个需求
    req2 = RequirementService.create_requirement(
        db,
        project_id=project.id,
        requirement_no="REQ-002",
        title="邮件发送功能",
        description="支持对接激活邮件发送",
        priority="HIGH",
        owner_id=user.id,
        actor_id=user.id,
        request_id="req-r2",
    )
    RequirementService.associate_to_version(
        db,
        project_id=project.id,
        requirement_id=req2.id,
        version_id=version.id,
        actor_id=user.id,
        request_id="req-r2-v1",
    )
    db.commit()

    now_time = datetime.now(UTC)
    task1 = TestTaskService.create_task(
        db,
        project_id=project.id,
        version_id=version.id,
        task_type="CASE_DESIGN",
        title="任务1",
        description="",
        priority="MEDIUM",
        owner_id=user.id,
        planned_start_at=now_time,
        planned_end_at=now_time + timedelta(days=2),
        test_goal=None,
        excluded_scope=None,
        tags_json=None,
        actor_id=user.id,
        request_id="req-t1",
        requirement_id=req.id,
    )
    db.commit()

    # 关联更换为需求2
    warnings = TestTaskService.update_requirements(
        db,
        project_id=project.id,
        task_id=task1.id,
        requirement_id=req2.id,
        actor_id=user.id,
        request_id="req-link-1",
    )
    db.commit()

    assert len(warnings) == 0  # 第一次关联无警告
    stmt = select(TestTaskRequirement.requirement_id).where(TestTaskRequirement.task_id == task1.id)
    assert db.scalar(stmt) == req2.id

    # 创建任务2，初始关联需求2
    task2 = TestTaskService.create_task(
        db,
        project_id=project.id,
        version_id=version.id,
        task_type="CASE_DESIGN",
        title="任务2",
        description="",
        priority="MEDIUM",
        owner_id=user.id,
        planned_start_at=now_time,
        planned_end_at=now_time + timedelta(days=2),
        test_goal=None,
        excluded_scope=None,
        tags_json=None,
        actor_id=user.id,
        request_id="req-t2",
        requirement_id=req2.id,
    )
    db.commit()

    # 任务2再次确认关联需求2，由于任务1已经关联了需求2，因此应当得到非阻断警告
    warnings = TestTaskService.update_requirements(
        db,
        project_id=project.id,
        task_id=task2.id,
        requirement_id=req2.id,
        actor_id=user.id,
        request_id="req-link-2",
    )
    db.commit()

    assert len(warnings) == 1
    assert warnings[0]["requirementNo"] == req2.requirement_no
    assert warnings[0]["taskNo"] == task1.task_no


def test_transition_matrix(db: Session, task_test_context: dict) -> None:
    user = task_test_context["user"]
    project = task_test_context["project"]
    version = task_test_context["version"]
    req = task_test_context["requirement"]

    now_time = datetime.now(UTC)
    task = TestTaskService.create_task(
        db,
        project_id=project.id,
        version_id=version.id,
        task_type="CASE_DESIGN",
        title="流转任务",
        description="",
        priority="MEDIUM",
        owner_id=user.id,
        planned_start_at=now_time,
        planned_end_at=now_time + timedelta(days=2),
        test_goal=None,
        excluded_scope=None,
        tags_json=None,
        actor_id=user.id,
        request_id="req-trans",
        requirement_id=req.id,
    )
    db.commit()

    # 手动删除关联关系以测试“无关联需求流转到 READY 报错”的情况
    db.query(TestTaskRequirement).filter(TestTaskRequirement.task_id == task.id).delete()
    db.flush()

    # 1. 尝试流转到READY，因为没有关联任何需求，应当报错
    with pytest.raises(AppError) as exc_info:
        TestTaskService.transition_status(
            db,
            project_id=project.id,
            task_id=task.id,
            target_status="READY",
            reason_code=None,
            reason_text=None,
            expected_row_version=task.row_version,
            actor_id=user.id,
            request_id="req-trans-err1",
        )
    assert exc_info.value.code == "TEST_TASK_REQUIREMENT_REQUIRED"

    # 关联需求
    TestTaskService.update_requirements(
        db,
        project_id=project.id,
        task_id=task.id,
        requirement_id=req.id,
        actor_id=user.id,
        request_id="req-trans-req-link",
    )
    db.commit()

    # 重新获取，因为刚才升级了row_version
    task = TestTaskService.get_task_by_id(db, project.id, task.id)

    # 2. 流转到READY
    task = TestTaskService.transition_status(
        db,
        project_id=project.id,
        task_id=task.id,
        target_status="READY",
        reason_code=None,
        reason_text=None,
        expected_row_version=task.row_version,
        actor_id=user.id,
        request_id="req-trans-ready",
    )
    db.commit()
    assert task.status == "READY"

    # 3. 流转到IN_PROGRESS
    task = TestTaskService.transition_status(
        db,
        project_id=project.id,
        task_id=task.id,
        target_status="IN_PROGRESS",
        reason_code=None,
        reason_text=None,
        expected_row_version=task.row_version,
        actor_id=user.id,
        request_id="req-trans-progress",
    )
    db.commit()
    assert task.status == "IN_PROGRESS"
    assert task.actual_started_at is not None

    # 4. 进入BLOCKED（必须传阻塞原因和说明）
    with pytest.raises(AppError) as exc_info:
        TestTaskService.transition_status(
            db,
            project_id=project.id,
            task_id=task.id,
            target_status="BLOCKED",
            reason_code=None,
            reason_text=None,
            expected_row_version=task.row_version,
            actor_id=user.id,
            request_id="req-trans-block-err",
        )
    assert exc_info.value.code == "TEST_TASK_BLOCK_REASON_REQUIRED"

    # 正常阻塞
    task = TestTaskService.transition_status(
        db,
        project_id=project.id,
        task_id=task.id,
        target_status="BLOCKED",
        reason_code="REQUIREMENT_UNCLEAR",
        reason_text="需求文档中第3点描述含糊",
        expected_row_version=task.row_version,
        actor_id=user.id,
        request_id="req-trans-block",
    )
    db.commit()
    assert task.status == "BLOCKED"

    # 验证有未解决阻塞
    block_rec = db.scalar(
        select(TestTaskBlockage).where(
            TestTaskBlockage.task_id == task.id, TestTaskBlockage.resolved_at.is_(None)
        )
    )
    assert block_rec is not None
    assert block_rec.reason_code == "REQUIREMENT_UNCLEAR"

    # 5. 解除阻塞（必须传解决说明）
    with pytest.raises(AppError) as exc_info:
        TestTaskService.transition_status(
            db,
            project_id=project.id,
            task_id=task.id,
            target_status="IN_PROGRESS",
            reason_code=None,
            reason_text=None,
            expected_row_version=task.row_version,
            actor_id=user.id,
            request_id="req-trans-unblock-err",
        )
    assert exc_info.value.code == "TEST_TASK_UNBLOCK_NOTE_REQUIRED"

    # 正常解除
    task = TestTaskService.transition_status(
        db,
        project_id=project.id,
        task_id=task.id,
        target_status="IN_PROGRESS",
        reason_code=None,
        reason_text="开发已口头澄清，不再存在疑问",
        expected_row_version=task.row_version,
        actor_id=user.id,
        request_id="req-trans-unblock",
    )
    db.commit()
    assert task.status == "IN_PROGRESS"

    # 验证阻塞已被解决
    assert (
        db.scalar(
            select(TestTaskBlockage).where(
                TestTaskBlockage.task_id == task.id, TestTaskBlockage.resolved_at.is_(None)
            )
        )
        is None
    )

    # 6. 完成任务
    task = TestTaskService.transition_status(
        db,
        project_id=project.id,
        task_id=task.id,
        target_status="COMPLETED",
        reason_code=None,
        reason_text="完成了本轮用例设计",
        expected_row_version=task.row_version,
        actor_id=user.id,
        request_id="req-trans-complete",
    )
    db.commit()
    assert task.status == "COMPLETED"
    assert task.current_completed_at is not None
    assert task.completion_count == 1

    # 7. 写保护测试：完成后修改基础信息被阻止
    with pytest.raises(AppError) as exc_info:
        TestTaskService.update_task(
            db,
            project_id=project.id,
            task_id=task.id,
            title="尝试修改标题",
            description="",
            priority="HIGH",
            owner_id=user.id,
            planned_start_at=task.planned_start_at,
            planned_end_at=task.planned_end_at,
            test_goal=None,
            excluded_scope=None,
            tags_json=None,
            expected_row_version=task.row_version,
            actor_id=user.id,
            request_id="req-task-update-comp-err",
        )
    assert exc_info.value.code == "TEST_TASK_ARCHIVED_READ_ONLY"

    # 8. 重新打开已完成任务 (必须传原因，必须是 admin/lead。这里传 is_admin_or_lead=True 模拟权限)
    with pytest.raises(AppError) as exc_info:
        TestTaskService.transition_status(
            db,
            project_id=project.id,
            task_id=task.id,
            target_status="IN_PROGRESS",
            reason_code=None,
            reason_text=None,
            expected_row_version=task.row_version,
            actor_id=user.id,
            request_id="req-trans-reopen-err",
            is_admin_or_lead=True,
        )
    assert exc_info.value.code == "TEST_TASK_REOPEN_REASON_REQUIRED"

    # 正常重新打开
    task = TestTaskService.transition_status(
        db,
        project_id=project.id,
        task_id=task.id,
        target_status="IN_PROGRESS",
        reason_code=None,
        reason_text="需求发生了变更，需要追加测试点",
        expected_row_version=task.row_version,
        actor_id=user.id,
        request_id="req-trans-reopen",
        is_admin_or_lead=True,
    )
    db.commit()
    assert task.status == "IN_PROGRESS"
    assert task.current_completed_at is None  # 重新打开清空

    # 9. 再次完成
    task = TestTaskService.transition_status(
        db,
        project_id=project.id,
        task_id=task.id,
        target_status="COMPLETED",
        reason_code=None,
        reason_text="完成变更后的补充设计",
        expected_row_version=task.row_version,
        actor_id=user.id,
        request_id="req-trans-complete2",
    )
    db.commit()
    assert task.status == "COMPLETED"
    assert task.completion_count == 2

    # 10. 归档
    task = TestTaskService.transition_status(
        db,
        project_id=project.id,
        task_id=task.id,
        target_status="ARCHIVED",
        reason_code=None,
        reason_text=None,
        expected_row_version=task.row_version,
        actor_id=user.id,
        request_id="req-trans-archive",
        is_admin_or_lead=True,
    )
    db.commit()
    assert task.status == "ARCHIVED"
    assert task.previous_status == "COMPLETED"
    assert task.archived_at is not None

    # 11. 恢复归档 (必须传原因，必须是 admin/lead)
    task = TestTaskService.transition_status(
        db,
        project_id=project.id,
        task_id=task.id,
        target_status="previous_status",
        reason_code=None,
        reason_text="需要查阅并重新分析此任务",
        expected_row_version=task.row_version,
        actor_id=user.id,
        request_id="req-trans-unarchive",
        is_admin_or_lead=True,
    )
    db.commit()
    assert task.status == "COMPLETED"
    assert task.archived_at is None
    assert task.previous_status is None
