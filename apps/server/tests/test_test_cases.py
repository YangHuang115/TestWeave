import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    TestCase,
    TestCaseEditSession,
    TestCaseRevision,
    TestCaseStep,
)
from testweave.modules.cases.service import CaseModuleService, TestCaseService
from testweave.modules.projects.service import ProjectService
from testweave.modules.users.service import UserService


@pytest.fixture
def case_test_context(db: Session) -> dict:
    """初始化用例测试上下文"""
    user = UserService.create_user(
        db,
        username="casetester",
        email="ct@testweave.com",
        display_name="Case Tester",
        password="test-password",
    )
    db.commit()

    user2 = UserService.create_user(
        db,
        username="casetester2",
        email="ct2@testweave.com",
        display_name="Case Tester 2",
        password="test-password",
    )
    db.commit()

    project = ProjectService.create_project(
        db,
        key="CTPROJ",
        name="Case Test Project",
        owner_id=user.id,
        request_id="req-cp1",
    )
    db.commit()

    return {
        "user": user,
        "user2": user2,
        "project": project,
    }


def test_create_case_success(db: Session, case_test_context: dict) -> None:
    user = case_test_context["user"]
    project = case_test_context["project"]

    steps = [
        {"action": "输入有效账号密码", "expected_result": "登录按钮高亮显示"},
        {"action": "点击登录", "expected_result": "登录成功，跳转至主页", "note": "需要配合验证码"},
    ]

    case = TestCaseService.create_case(
        db,
        project_id=project.id,
        title="用户登录测试用例",
        precondition="用户处于登录页面且网络正常",
        priority="HIGH",
        case_type="FUNCTIONAL",
        tags_json=["登录", "核心"],
        test_data_note="账号: test, 密码: 123",
        note="暂无备注",
        steps=steps,
        source_task_id=None,
        actor_id=user.id,
        request_id="req-case-c1",
    )
    db.commit()

    assert case.id is not None
    assert case.case_no == "TC-000001"
    assert case.row_version == 1
    assert case.current_revision_id is not None

    # 验证步骤
    steps_db = db.scalars(
        select(TestCaseStep)
        .where(TestCaseStep.case_id == case.id)
        .order_by(TestCaseStep.step_order)
    ).all()
    assert len(steps_db) == 2
    assert steps_db[0].action == "输入有效账号密码"
    assert steps_db[0].step_order == 1
    assert steps_db[1].note == "需要配合验证码"

    # 验证初始修订历史 (Revision 1)
    revision = db.get(TestCaseRevision, case.current_revision_id)
    assert revision is not None
    assert revision.revision_no == 1
    assert revision.snapshot["title"] == "用户登录测试用例"
    assert len(revision.snapshot["steps"]) == 2
    assert revision.snapshot["steps"][0]["action"] == "输入有效账号密码"


def test_concurrency_case_no(db: Session, case_test_context: dict) -> None:
    user = case_test_context["user"]
    project = case_test_context["project"]

    # 创建第一个用例
    case1 = TestCaseService.create_case(
        db,
        project_id=project.id,
        title="测试用例1",
        precondition=None,
        priority="LOW",
        case_type="FUNCTIONAL",
        tags_json=[],
        test_data_note=None,
        note=None,
        steps=[],
        source_task_id=None,
        actor_id=user.id,
        request_id="req-case-num1",
    )

    # 创建第二个用例
    case2 = TestCaseService.create_case(
        db,
        project_id=project.id,
        title="测试用例2",
        precondition=None,
        priority="MEDIUM",
        case_type="FUNCTIONAL",
        tags_json=[],
        test_data_note=None,
        note=None,
        steps=[],
        source_task_id=None,
        actor_id=user.id,
        request_id="req-case-num2",
    )
    db.commit()

    assert case1.case_no == "TC-000001"
    assert case2.case_no == "TC-000002"


def test_edit_session_lifecycle(db: Session, case_test_context: dict) -> None:
    user = case_test_context["user"]
    user2 = case_test_context["user2"]
    project = case_test_context["project"]

    case = TestCaseService.create_case(
        db,
        project_id=project.id,
        title="原标题",
        precondition="原前置条件",
        priority="LOW",
        case_type="FUNCTIONAL",
        tags_json=["原标签"],
        test_data_note=None,
        note=None,
        steps=[{"action": "第一步", "expected_result": "通过"}],
        source_task_id=None,
        actor_id=user.id,
        request_id="req-case-lifecycle",
    )
    db.commit()

    # 1. 开启会话
    session = TestCaseService.start_edit_session(db, project.id, case.id, user.id)
    db.commit()

    assert session.id is not None
    assert session.status == "OPEN"
    assert session.base_row_version == 1

    # 2. 幂等测试：同用户再次进入返回同一个会话
    session_again = TestCaseService.start_edit_session(db, project.id, case.id, user.id)
    assert session_again.id == session.id

    # 3. 冲突测试：其它用户不能强抢正在打开的活跃会话
    with pytest.raises(AppError) as exc_info:
        TestCaseService.start_edit_session(db, project.id, case.id, user2.id)
    assert exc_info.value.code == "CASE_EDIT_SESSION_CONFLICT"

    # 4. 暂存修改 (更新 title)
    TestCaseService.update_session_draft(
        db,
        project_id=project.id,
        case_id=case.id,
        session_id=session.id,
        dirty_fields={"title": "更新后的标题", "tags_json": ["新标签"]},
        actor_id=user.id,
    )
    db.commit()

    # 重新加载，验证暂存
    session = db.get(TestCaseEditSession, session.id)
    assert session.dirty_fields["title"] == "更新后的标题"
    assert session.dirty_fields["tags_json"] == ["新标签"]

    # 5. 再次暂存修改 (更新 steps)
    TestCaseService.update_session_draft(
        db,
        project_id=project.id,
        case_id=case.id,
        session_id=session.id,
        dirty_fields={
            "steps": [
                {"action": "新第一步", "expected_result": "通过"},
                {"action": "新第二步", "expected_result": "成功"},
            ]
        },
        actor_id=user.id,
    )
    db.commit()

    # 6. 合并提交会话
    revision = TestCaseService.finalize_edit_session(
        db,
        project_id=project.id,
        case_id=case.id,
        session_id=session.id,
        actor_id=user.id,
        change_summary={"type": "UPDATE", "note": "修改标题与步骤"},
    )
    db.commit()

    assert revision.revision_no == 2
    assert session.status == "FINALIZED"
    assert session.finalized_at is not None

    # 验证用例属性已更新
    case = db.get(TestCase, case.id)
    assert case.title == "更新后的标题"
    assert case.row_version == 2
    assert case.current_revision_id == revision.id

    # 验证步骤已变动
    steps_db = db.scalars(
        select(TestCaseStep)
        .where(TestCaseStep.case_id == case.id)
        .order_by(TestCaseStep.step_order)
    ).all()
    assert len(steps_db) == 2
    assert steps_db[0].action == "新第一步"
    assert steps_db[1].action == "新第二步"


def test_edit_session_optimistic_lock(db: Session, case_test_context: dict) -> None:
    user = case_test_context["user"]
    user2 = case_test_context["user2"]
    project = case_test_context["project"]

    case = TestCaseService.create_case(
        db,
        project_id=project.id,
        title="共享原标题",
        precondition=None,
        priority="LOW",
        case_type="FUNCTIONAL",
        tags_json=[],
        test_data_note=None,
        note=None,
        steps=[],
        source_task_id=None,
        actor_id=user.id,
        request_id="req-case-lock",
    )
    db.commit()

    # 会话1：用户1开启
    session1 = TestCaseService.start_edit_session(db, project.id, case.id, user.id)
    TestCaseService.update_session_draft(
        db,
        project.id,
        case.id,
        session1.id,
        {"title": "用户1修改的标题"},
        user.id,
    )
    db.commit()

    # 为了模拟并发，我们手动将 session1 置为 FINALIZED (或者在正常流程下提交它)，
    # 因为 start_edit_session 会在有 OPEN 状态其它人会话时报错，
    # 我们可以通过以下步骤测试乐观锁冲突：
    # 1. 提交会话 1
    TestCaseService.finalize_edit_session(
        db,
        project.id,
        case.id,
        session1.id,
        user.id,
        {"note": "用户1完成"},
    )
    db.commit()
    # 此时用例已更新，row_version 自增至 2

    # 2. 会话 2：由于会话 1 已经 finalized 了，用户 2 此时可以通过
    # start_edit_session 重新启动一个会话。但我们如果要验证乐观锁冲突
    # （即用户 2 在旧版本上编辑），实际上当用户 2 在用户 1 提交前启动的会话：
    # 让我们还原场景：
    # 在用户 1 提交前，用户 2 是无法启动新会话的（会被 start_edit_session
    # 的 OPEN 冲突拦截）。但是，有一种可能：当用户 1 启动了会话 1
    # 并 finalized 之后，用户 2 启动了会话 2（基于 base_row_version=2）。
    # 如果用户 2 的会话 2 启动后，有其它渠道的修改（如后台脚本）更新了
    # row_version，那么用户 2 就会被乐观锁拦截。
    # 我们也可以直接在测试里手动构造一个“拥有陈旧 base_row_version 的会话”！
    # 这样可以 100% 确认 finalize_edit_session 的乐观锁比对机制正常工作。

    # 手动创建一个陈旧会话（基于 base_row_version = 1）
    stale_session = TestCaseEditSession(
        case_id=case.id,
        actor_id=user2.id,
        base_revision_id=case.current_revision_id,  # 虽然 ID 可以是最新的，但版本号不一致
        base_row_version=1,  # 故意设为旧版 (目前实际 row_version 已经是 2)
        status="OPEN",
        dirty_fields={"title": "用户2尝试覆盖的标题"},
    )
    db.add(stale_session)
    db.commit()

    # 用户 2 尝试提交这个陈旧会话，应当触发乐观锁冲突报错
    with pytest.raises(AppError) as exc_info:
        TestCaseService.finalize_edit_session(
            db,
            project.id,
            case.id,
            stale_session.id,
            user2.id,
            {"note": "用户2覆盖"},
        )
    assert exc_info.value.code == "CASE_OPTIMISTIC_LOCK_CONFLICT"


def test_module_crud_and_validation(db: Session, case_test_context: dict) -> None:
    project = case_test_context["project"]

    # 1. 成功创建根模块和子模块
    m1 = CaseModuleService.create_module(db, project.id, "支付模块", description="测试支付")
    m2 = CaseModuleService.create_module(
        db, project.id, "支付宝通道", parent_id=m1.id, description="测试支付宝"
    )
    db.commit()

    assert m1.id is not None
    assert m1.parent_id is None
    assert m2.parent_id == m1.id

    # 2. 同级重名冲突测试
    with pytest.raises(AppError) as exc_info:
        CaseModuleService.create_module(db, project.id, "支付宝通道", parent_id=m1.id)
    assert exc_info.value.code == "CASE_MODULE_NAME_DUPLICATED"

    # 3. 跨级重名（在不同父模块下），应当允许
    other_root = CaseModuleService.create_module(db, project.id, "其它模块")
    m3 = CaseModuleService.create_module(db, project.id, "支付宝通道", parent_id=other_root.id)
    db.commit()
    assert m3.id is not None

    # 4. 修改模块信息（重命名冲突）
    CaseModuleService.create_module(db, project.id, "微信通道", parent_id=m1.id)
    db.commit()

    # 将 m2 ("支付宝通道") 修改为同级的 "微信通道" 应当报错
    with pytest.raises(AppError) as exc_info:
        CaseModuleService.update_module(db, project.id, m2.id, "微信通道")
    assert exc_info.value.code == "CASE_MODULE_NAME_DUPLICATED"


def test_module_tree_generation(db: Session, case_test_context: dict) -> None:
    project = case_test_context["project"]

    # 创建树：
    # 根模块 A (sort_order=2)
    # 根模块 B (sort_order=1) -> 子模块 B1
    CaseModuleService.create_module(db, project.id, "模块A", sort_order=2)
    root_b = CaseModuleService.create_module(db, project.id, "模块B", sort_order=1)
    CaseModuleService.create_module(db, project.id, "子模块B1", parent_id=root_b.id, sort_order=1)
    db.commit()

    tree = CaseModuleService.get_module_tree(db, project.id)
    # 因为 sort_order，B 排在 A 前面
    assert len(tree) == 2
    assert tree[0]["name"] == "模块B"
    assert tree[1]["name"] == "模块A"
    assert len(tree[0]["children"]) == 1
    assert tree[0]["children"][0]["name"] == "子模块B1"


def test_module_move_cyclic_check(db: Session, case_test_context: dict) -> None:
    project = case_test_context["project"]

    # 结构：A -> B -> C
    mod_a = CaseModuleService.create_module(db, project.id, "模块A")
    mod_b = CaseModuleService.create_module(db, project.id, "模块B", parent_id=mod_a.id)
    mod_c = CaseModuleService.create_module(db, project.id, "模块C", parent_id=mod_b.id)
    db.commit()

    # 1. 尝试将 A 移到自身之下 -> 报错
    with pytest.raises(AppError) as exc_info:
        CaseModuleService.move_module(db, project.id, mod_a.id, mod_a.id)
    assert exc_info.value.code == "CASE_MODULE_CYCLIC_DEPENDENCY"

    # 2. 尝试将 A 移到其子节点 C 之下 -> 报错
    with pytest.raises(AppError) as exc_info:
        CaseModuleService.move_module(db, project.id, mod_a.id, mod_c.id)
    assert exc_info.value.code == "CASE_MODULE_CYCLIC_DEPENDENCY"

    # 3. 正常移动：将 C 移到 A 之下 (平行于 B)
    moved = CaseModuleService.move_module(db, project.id, mod_c.id, mod_a.id)
    db.commit()
    assert moved.parent_id == mod_a.id


def test_module_archive_restrictions(db: Session, case_test_context: dict) -> None:
    user = case_test_context["user"]
    project = case_test_context["project"]

    mod_parent = CaseModuleService.create_module(db, project.id, "父模块")
    mod_child = CaseModuleService.create_module(db, project.id, "子模块", parent_id=mod_parent.id)
    db.commit()

    # 1. 尝试归档父模块 (有子模块存在，禁止)
    with pytest.raises(AppError) as exc_info:
        CaseModuleService.archive_module(db, project.id, mod_parent.id)
    assert exc_info.value.code == "CASE_MODULE_HAS_CHILDREN"

    # 2. 创建一个用例并关联到子模块
    TestCaseService.create_case(
        db,
        project_id=project.id,
        title="关联测试用例",
        precondition=None,
        priority="LOW",
        case_type="FUNCTIONAL",
        tags_json=[],
        test_data_note=None,
        note=None,
        steps=[],
        source_task_id=None,
        actor_id=user.id,
        request_id="req-case-link-mod",
        module_ids=[str(mod_child.id)],
    )
    db.commit()

    # 3. 尝试归档子模块 (有用例关联，禁止)
    with pytest.raises(AppError) as exc_info:
        CaseModuleService.archive_module(db, project.id, mod_child.id)
    assert exc_info.value.code == "CASE_MODULE_HAS_TEST_CASES"

    # 4. 正常归档无关联的空模块
    mod_empty = CaseModuleService.create_module(db, project.id, "空模块")
    db.commit()
    archived = CaseModuleService.archive_module(db, project.id, mod_empty.id)
    db.commit()
    assert archived.archived_at is not None
