from typing import ClassVar

from testweave.core.errors import AppError
from testweave.modules.ai_capability.enums import CapabilityRunStatus, StepExecutionStatus


class StateMachine:
    """Run 与 Step Attempt 严格状态转移状态机"""

    VALID_RUN_TRANSITIONS: ClassVar[dict[CapabilityRunStatus, set[CapabilityRunStatus]]] = {
        CapabilityRunStatus.PENDING: {
            CapabilityRunStatus.RUNNING,
            CapabilityRunStatus.WAITING_EXTERNAL_AGENT,
            CapabilityRunStatus.CANCELLED,
        },
        CapabilityRunStatus.RUNNING: {
            CapabilityRunStatus.WAITING_EXTERNAL_AGENT,
            CapabilityRunStatus.WAITING_HUMAN,
            CapabilityRunStatus.WAITING_RETRY,
            CapabilityRunStatus.SUCCEEDED,
            CapabilityRunStatus.FAILED,
            CapabilityRunStatus.CANCELLED,
        },
        CapabilityRunStatus.WAITING_EXTERNAL_AGENT: {
            CapabilityRunStatus.WAITING_HUMAN,
            CapabilityRunStatus.WAITING_RETRY,
            CapabilityRunStatus.RUNNING,
            CapabilityRunStatus.FAILED,
            CapabilityRunStatus.CANCELLED,
        },
        CapabilityRunStatus.WAITING_HUMAN: {
            CapabilityRunStatus.RUNNING,
            CapabilityRunStatus.WAITING_RETRY,
            CapabilityRunStatus.FAILED,
            CapabilityRunStatus.CANCELLED,
        },
        CapabilityRunStatus.WAITING_RETRY: {
            CapabilityRunStatus.RUNNING,
            CapabilityRunStatus.WAITING_EXTERNAL_AGENT,
            CapabilityRunStatus.FAILED,
            CapabilityRunStatus.CANCELLED,
        },
        CapabilityRunStatus.SUCCEEDED: set(),
        CapabilityRunStatus.FAILED: set(),
        CapabilityRunStatus.CANCELLED: set(),
    }

    VALID_STEP_TRANSITIONS: ClassVar[dict[StepExecutionStatus, set[StepExecutionStatus]]] = {
        StepExecutionStatus.PENDING: {
            StepExecutionStatus.RUNNING,
            StepExecutionStatus.WAITING_EXTERNAL_AGENT,
            StepExecutionStatus.CANCELLED,
            StepExecutionStatus.SKIPPED,
        },
        StepExecutionStatus.RUNNING: {
            StepExecutionStatus.WAITING_EXTERNAL_AGENT,
            StepExecutionStatus.WAITING_HUMAN,
            StepExecutionStatus.WAITING_RETRY,
            StepExecutionStatus.SUCCEEDED,
            StepExecutionStatus.FAILED,
            StepExecutionStatus.CANCELLED,
        },
        StepExecutionStatus.WAITING_EXTERNAL_AGENT: {
            StepExecutionStatus.SUCCEEDED,
            StepExecutionStatus.WAITING_RETRY,
            StepExecutionStatus.FAILED,
            StepExecutionStatus.CANCELLED,
        },
        StepExecutionStatus.WAITING_HUMAN: {
            StepExecutionStatus.SUCCEEDED,
            StepExecutionStatus.WAITING_RETRY,
            StepExecutionStatus.FAILED,
            StepExecutionStatus.CANCELLED,
        },
        StepExecutionStatus.WAITING_RETRY: {
            StepExecutionStatus.RUNNING,
            StepExecutionStatus.WAITING_EXTERNAL_AGENT,
            StepExecutionStatus.FAILED,
            StepExecutionStatus.CANCELLED,
        },
        StepExecutionStatus.SUCCEEDED: set(),
        StepExecutionStatus.FAILED: set(),
        StepExecutionStatus.CANCELLED: set(),
        StepExecutionStatus.SKIPPED: set(),
    }

    @classmethod
    def validate_run_transition(
        cls, current: CapabilityRunStatus | str, target: CapabilityRunStatus | str
    ) -> None:
        curr_enum = CapabilityRunStatus(current)
        targ_enum = CapabilityRunStatus(target)

        if targ_enum == CapabilityRunStatus.WAITING_EXTERNAL_AGENT:
            raise AppError(
                code="EXTERNAL_WORKER_RETIRED",
                message="旧版外部 Agent Worker 已退役，禁止新产生 WAITING_EXTERNAL_AGENT 状态",
                status_code=400,
            )

        if targ_enum not in cls.VALID_RUN_TRANSITIONS.get(curr_enum, set()):
            raise AppError(
                code="RUN_STATE_TRANSITION_INVALID",
                message=f"非法 Run 状态转移: {curr_enum} -> {targ_enum}",
                status_code=400,
            )

    @classmethod
    def validate_step_transition(
        cls, current: StepExecutionStatus | str, target: StepExecutionStatus | str
    ) -> None:
        curr_enum = StepExecutionStatus(current)
        targ_enum = StepExecutionStatus(target)

        if targ_enum == StepExecutionStatus.WAITING_EXTERNAL_AGENT:
            raise AppError(
                code="EXTERNAL_WORKER_RETIRED",
                message="旧版外部 Agent Worker 已退役，禁止新产生 WAITING_EXTERNAL_AGENT 步骤",
                status_code=400,
            )

        if targ_enum not in cls.VALID_STEP_TRANSITIONS.get(curr_enum, set()):
            raise AppError(
                code="RUN_STATE_TRANSITION_INVALID",
                message=f"非法 Step 状态转移: {curr_enum} -> {targ_enum}",
                status_code=400,
            )

    @classmethod
    def is_run_terminal(cls, status: CapabilityRunStatus | str) -> bool:
        enum_val = CapabilityRunStatus(status)
        return enum_val in {
            CapabilityRunStatus.SUCCEEDED,
            CapabilityRunStatus.FAILED,
            CapabilityRunStatus.CANCELLED,
        }

    @classmethod
    def is_step_terminal(cls, status: StepExecutionStatus | str) -> bool:
        enum_val = StepExecutionStatus(status)
        return enum_val in {
            StepExecutionStatus.SUCCEEDED,
            StepExecutionStatus.FAILED,
            StepExecutionStatus.CANCELLED,
            StepExecutionStatus.SKIPPED,
        }
