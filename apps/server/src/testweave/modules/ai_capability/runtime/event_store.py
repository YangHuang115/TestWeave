import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.db.models import AICapabilityRun, AIRunEvent
from testweave.modules.ai_capability.enums import AIRunEventType


class EventStore:
    """Run 事件原子写与游标轮询存取器"""

    @classmethod
    def emit_event(
        cls,
        db: Session,
        run: AICapabilityRun,
        event_type: AIRunEventType | str,
        payload: dict[str, Any] | None = None,
        step_execution_id: uuid.UUID | None = None,
    ) -> AIRunEvent:
        """原子锁定并发递增 sequence 写事件"""
        # 使用 select ... for update 锁定 run 记录
        locked_run = db.scalar(
            select(AICapabilityRun).where(AICapabilityRun.id == run.id).with_for_update()
        )
        if not locked_run:
            locked_run = run

        curr_seq = locked_run.next_event_sequence
        locked_run.next_event_sequence = curr_seq + 1

        clean_payload = payload or {}
        # 安全清洗: 确保不放 Prompt, Secret, Auth Key
        clean_payload.pop("api_key", None)
        clean_payload.pop("prompt", None)
        clean_payload.pop("credentials", None)

        event = AIRunEvent(
            run_id=locked_run.id,
            step_execution_id=step_execution_id,
            sequence=curr_seq,
            event_type=str(event_type),
            trace_id=locked_run.trace_id,
            payload=clean_payload,
        )
        db.add(event)
        db.flush()
        return event

    @classmethod
    def query_events_after(
        cls,
        db: Session,
        run_id: uuid.UUID,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> list[AIRunEvent]:
        """游标轮询查询指定 sequence 之后的事件"""
        safe_limit = min(max(limit, 1), 200)
        stmt = (
            select(AIRunEvent)
            .where(
                AIRunEvent.run_id == run_id,
                AIRunEvent.sequence > after_sequence,
            )
            .order_by(AIRunEvent.sequence.asc())
            .limit(safe_limit)
        )
        return list(db.scalars(stmt).all())
