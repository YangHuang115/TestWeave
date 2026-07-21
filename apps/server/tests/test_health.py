from collections.abc import Mapping
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine

from testweave.core.readiness import ReadinessFailure, SqlAlchemyReadinessProbe
from testweave.main import create_app

pytestmark = pytest.mark.anyio


class ReadyProbe:
    def check(self) -> Mapping[str, str]:
        return {"database": "ok", "migrations": "ok"}


class UnavailableProbe:
    def check(self) -> Mapping[str, str]:
        raise ReadinessFailure("connection to postgresql://secret@db failed")


async def test_live_reports_process_health_without_dependency_details() -> None:
    transport = ASGITransport(app=create_app(readiness_probe=ReadyProbe()))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"].startswith("req_")


async def test_ready_reports_database_and_migration_state() -> None:
    transport = ASGITransport(app=create_app(readiness_probe=ReadyProbe()))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"database": "ok", "migrations": "ok"},
    }


async def test_ready_returns_retryable_standard_error_without_leaking_database_details() -> None:
    transport = ASGITransport(app=create_app(readiness_probe=UnavailableProbe()))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "code": "SERVICE_NOT_READY",
        "message": "服务暂未就绪，请稍后重试",
        "requestId": response.headers["x-request-id"],
        "retryable": True,
        "details": None,
    }
    assert "secret" not in response.text
    assert "postgresql" not in response.text


async def test_ready_maps_missing_alembic_configuration_to_service_not_ready(
    tmp_path: Path,
) -> None:
    engine = create_engine("sqlite://")
    probe = SqlAlchemyReadinessProbe(engine, tmp_path / "missing-alembic.ini")
    transport = ASGITransport(app=create_app(readiness_probe=probe))

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health/ready")
    finally:
        engine.dispose()

    assert response.status_code == 503
    assert response.json()["code"] == "SERVICE_NOT_READY"
    assert response.json()["requestId"] == response.headers["x-request-id"]
