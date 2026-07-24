import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import IdempotencyKey


class IdempotencyService:
    @staticmethod
    def compute_request_hash(payload: Any) -> str:
        """使用 SHA-256 计算请求 Payload 的确定性 Hash"""
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def resolve_key(header_key: str | None, body_key: str | None) -> str | None:
        """解析并校验 Header 与 Body 幂等键的一致性"""
        h_key = header_key.strip() if header_key and header_key.strip() else None
        b_key = body_key.strip() if body_key and body_key.strip() else None

        if h_key and b_key and h_key != b_key:
            raise AppError(
                code="IDEMPOTENCY_KEY_MISMATCH",
                message=f"Header 中的 Idempotency-Key ({h_key}) 与 Body 中的 idempotencyKey ({b_key}) 不一致",
                status_code=400,
            )

        return h_key or b_key

    @classmethod
    def check_existing(
        cls,
        db: Session,
        project_id: uuid.UUID,
        endpoint: str,
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, Any] | None:
        """检查是否有已存在的幂等记录；冲突抛出 409，命中返回回放响应"""
        stmt = select(IdempotencyKey).where(
            IdempotencyKey.project_id == project_id,
            IdempotencyKey.endpoint == endpoint,
            IdempotencyKey.idempotency_key == idempotency_key,
        )
        existing = db.scalar(stmt)
        if not existing:
            return None

        if existing.request_hash != request_hash:
            raise AppError(
                code="IDEMPOTENCY_KEY_REUSED",
                message=f"幂等键 '{idempotency_key}' 已在不同的请求内容中被使用，禁止复用",
                status_code=409,
            )

        return dict(existing.response_json)

    @classmethod
    def record_response(
        cls,
        db: Session,
        project_id: uuid.UUID,
        endpoint: str,
        idempotency_key: str,
        request_hash: str,
        response_json: dict[str, Any],
    ) -> None:
        """记录并持久化保存响应结果以供后续幂等重放"""
        try:
            record = IdempotencyKey(
                project_id=project_id,
                endpoint=endpoint,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                response_json=response_json,
            )
            db.add(record)
            db.commit()
        except IntegrityError:
            db.rollback()
            # 并发竞争场景：已有其它进程抢先写入，查询并验证
            stmt = select(IdempotencyKey).where(
                IdempotencyKey.project_id == project_id,
                IdempotencyKey.endpoint == endpoint,
                IdempotencyKey.idempotency_key == idempotency_key,
            )
            existing = db.scalar(stmt)
            if existing and existing.request_hash != request_hash:
                raise AppError(
                    code="IDEMPOTENCY_KEY_REUSED",
                    message=f"幂等键 '{idempotency_key}' 已在不同的请求内容中被使用，禁止复用",
                    status_code=409,
                ) from None
