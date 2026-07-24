import pytest

from testweave.core.errors import AppError
from testweave.modules.ai_capability.enums import (
    CapabilityRunStatus,
    HumanAction,
)
from testweave.modules.ai_capability.runtime.executors.human import HumanExecutor
from testweave.modules.ai_capability.runtime.executors.skill import SkillExecutor
from testweave.modules.ai_capability.runtime.executors.transform import TransformExecutor
from testweave.modules.ai_capability.runtime.executors.validator import ValidatorExecutor
from testweave.modules.ai_capability.runtime.graph import WorkflowGraph
from testweave.modules.ai_capability.runtime.input_mapping import (
    InputMappingDSL,
    resolve_json_pointer,
)
from testweave.modules.ai_capability.runtime.provider import (
    FakeModelProvider,
)
from testweave.modules.ai_capability.runtime.snapshots import (
    calculate_json_hash,
)
from testweave.modules.ai_capability.runtime.state_machine import StateMachine


def test_state_machine_validations() -> None:
    # 合法转移
    StateMachine.validate_run_transition(CapabilityRunStatus.PENDING, CapabilityRunStatus.RUNNING)
    StateMachine.validate_run_transition(
        CapabilityRunStatus.RUNNING, CapabilityRunStatus.WAITING_HUMAN
    )
    StateMachine.validate_run_transition(
        CapabilityRunStatus.WAITING_HUMAN, CapabilityRunStatus.RUNNING
    )
    StateMachine.validate_run_transition(CapabilityRunStatus.RUNNING, CapabilityRunStatus.SUCCEEDED)

    # 包含外部 Agent 状态在 P2 拒绝
    with pytest.raises(AppError) as exc:
        StateMachine.validate_run_transition(
            CapabilityRunStatus.RUNNING, CapabilityRunStatus.WAITING_EXTERNAL_AGENT
        )
    assert exc.value.code == "EXTERNAL_WORKER_RETIRED"

    # 非法转移拒绝
    with pytest.raises(AppError) as exc2:
        StateMachine.validate_run_transition(
            CapabilityRunStatus.SUCCEEDED, CapabilityRunStatus.RUNNING
        )
    assert exc2.value.code == "RUN_STATE_TRANSITION_INVALID"


def test_input_mapping_json_pointer() -> None:
    doc = {
        "user": {"name": "Alice", "skills": ["python", "testing"]},
        "details": {"score": 95},
    }
    assert resolve_json_pointer(doc, "") == doc
    assert resolve_json_pointer(doc, "/user/name") == "Alice"
    assert resolve_json_pointer(doc, "/user/skills/1") == "testing"

    with pytest.raises(AppError):
        resolve_json_pointer(doc, "/user/not_exist")


def test_input_mapping_dsl() -> None:
    cap_input = {"req": "设计登录流程需求"}
    upstream_outputs = {
        "node1": {"questions": ["问题1", "问题2"]},
    }

    # 整个输入引用
    res1 = InputMappingDSL.resolve_mapping("capability.input", cap_input, upstream_outputs, set())
    assert res1 == cap_input

    # 指针引用
    res2 = InputMappingDSL.resolve_mapping(
        "capability.input#/req", cap_input, upstream_outputs, set()
    )
    assert res2 == "设计登录流程需求"

    # 上游输出引用
    res3 = InputMappingDSL.resolve_mapping(
        "node1.output#/questions/0", cap_input, upstream_outputs, {"node1"}
    )
    assert res3 == "问题1"

    # 访问非上游节点拒绝
    with pytest.raises(AppError) as exc:
        InputMappingDSL.resolve_mapping("node2.output", cap_input, upstream_outputs, {"node1"})
    assert exc.value.code == "RUN_INPUT_SCHEMA_INVALID"


def test_workflow_graph_dag_checks() -> None:
    # 正常 DAG
    valid_wf = {
        "nodes": {
            "n1": {"type": "SKILL", "input": "capability.input"},
            "n2": {"type": "HUMAN", "input": "n1.output"},
            "n3": {"type": "VALIDATOR", "input": "n2.output"},
        }
    }
    graph = WorkflowGraph(valid_wf)
    assert graph.sink_node_id == "n3"
    assert graph.get_runnable_nodes(set(), {"n1", "n2", "n3"}) == ["n1"]
    assert graph.get_runnable_nodes({"n1"}, {"n2", "n3"}) == ["n2"]

    # 自环 / 环路拒绝
    loop_wf = {
        "nodes": {
            "n1": {"type": "SKILL", "input": "n2.output"},
            "n2": {"type": "SKILL", "input": "n1.output"},
        }
    }
    with pytest.raises(AppError) as exc:
        WorkflowGraph(loop_wf)
    assert exc.value.code == "RUN_CAPABILITY_NOT_RUNNABLE"

    # 多终端节点拒绝
    multi_sink_wf = {
        "nodes": {
            "n1": {"type": "SKILL", "input": "capability.input"},
            "n2": {"type": "SKILL", "input": "n1.output"},
            "n3": {"type": "SKILL", "input": "n1.output"},
        }
    }
    with pytest.raises(AppError) as exc2:
        WorkflowGraph(multi_sink_wf)
    assert exc2.value.code == "RUN_CAPABILITY_NOT_RUNNABLE"


@pytest.mark.anyio
async def test_executors_behavior() -> None:
    fake_provider = FakeModelProvider(
        {"SKILL_PROMPT": {"test_points": [{"id": 1, "source_ref": "REQ-1"}]}}
    )

    # 1. Skill Executor
    skill_exec = SkillExecutor()
    res1 = await skill_exec.execute(
        node_id="n1",
        node_def={
            "type": "SKILL",
            "output_schema": {"type": "object", "properties": {"test_points": {"type": "array"}}},
        },
        resolved_input={"input": "test"},
        execution_snapshot={"package_files": {"SKILL.md": "SKILL_PROMPT"}},
        provider=fake_provider,
    )
    assert "test_points" in res1.output

    # 2. Transform Executor
    trans_exec = TransformExecutor()
    res2 = await trans_exec.execute(
        node_id="n2",
        node_def={
            "type": "TRANSFORM",
            "operation": "rename_keys",
            "config": {"mapping": {"old_key": "new_key"}},
        },
        resolved_input={"old_key": "value"},
        execution_snapshot={},
        provider=fake_provider,
    )
    assert res2.output == {"new_key": "value"}

    # 3. Validator Executor
    val_exec = ValidatorExecutor()
    res3 = await val_exec.execute(
        node_id="n3",
        node_def={"type": "VALIDATOR", "rules": ["every_item_has_source_reference"]},
        resolved_input={"test_points": [{"id": 1, "source_reference": "REQ-10001"}]},
        execution_snapshot={},
        provider=fake_provider,
    )
    assert res3.validator_results["valid"] is True

    # 失败 Validator
    res3_fail = await val_exec.execute(
        node_id="n3",
        node_def={"type": "VALIDATOR", "rules": ["every_item_has_source_reference"]},
        resolved_input={"test_points": [{"id": 2}]},
        execution_snapshot={},
        provider=fake_provider,
    )
    assert res3_fail.validator_results["valid"] is False
    assert res3_fail.error_code == "RUN_VALIDATOR_FAILED"

    # 4. Human Executor
    human_exec = HumanExecutor()
    res4_wait = await human_exec.execute(
        node_id="n4",
        node_def={"type": "HUMAN"},
        resolved_input={"data": 1},
        execution_snapshot={},
        provider=fake_provider,
        human_decision=None,
    )
    assert res4_wait.waiting_human is True

    res4_continue = await human_exec.execute(
        node_id="n4",
        node_def={"type": "HUMAN"},
        resolved_input={"data": 1},
        execution_snapshot={},
        provider=fake_provider,
        human_decision={"action": HumanAction.CONTINUE, "decision": {"confirmed": True}},
    )
    assert res4_continue.output == {"confirmed": True}


def test_snapshots_hash_calculation() -> None:
    data1 = {"a": 1, "b": 2}
    data2 = {"b": 2, "a": 1}
    assert calculate_json_hash(data1) == calculate_json_hash(data2)
