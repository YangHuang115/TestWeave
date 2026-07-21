import uuid
from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from testweave.db.models import AuditEvent


class AuditService:
    @staticmethod
    def log_event(
        db: Session,
        *,
        action: str,
        object_type: str,
        object_id: str,
        summary: str,
        request_id: str,
        project_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> AuditEvent:
        """记录一个审计事件"""
        event = AuditEvent(
            project_id=project_id,
            actor_id=actor_id,
            action=action,
            object_type=object_type,
            object_id=object_id,
            summary=summary,
            request_id=request_id,
            created_at=datetime.now(UTC),
        )
        db.add(event)
        # 审计日志通常直接跟当前事务一起提交，所以这里不需要 db.commit()，交给外部的事务边界管理
        return event

    @staticmethod
    def list_project_events(
        db: Session,
        *,
        project_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditEvent]:
        """获取项目相关的审计日志列表，按时间降序排列"""
        stmt = (
            select(AuditEvent)
            .where(AuditEvent.project_id == project_id)
            .order_by(desc(AuditEvent.created_at))
            .offset(offset)
            .limit(limit)
        )
        return list(db.scalars(stmt).all())
