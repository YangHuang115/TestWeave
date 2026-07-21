import json
from collections.abc import Mapping

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from testweave.core.errors import AppError
from testweave.main import create_app

pytestmark = pytest.mark.anyio


class ReadyProbe:
    def check(self) -> Mapping[str, str]:
        return {"database": "ok", "migrations": "ok"}


def app_with_failure_route() -> FastAPI:
    app = create_app(readiness_probe=ReadyProbe())

    @app.get("/_test/conflict")
    def conflict() -> None:
        raise AppError(
            code="RESOURCE_CONFLICT",
            message="资源已被其他请求修改",
            status_code=409,
            details={"field": "revision"},
        )

    return app


def app_with_unhandled_route() -> FastAPI:
    app = create_app(readiness_probe=ReadyProbe())

    @app.get("/_test/unhandled")
    def unhandled() -> None:
        raise RuntimeError("sensitive diagnostic detail")

    return app


async def test_error_body_and_response_header_share_valid_client_request_id() -> None:
    transport = ASGITransport(app=app_with_failure_route())

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/_test/conflict",
            headers={"X-Request-ID": "client_request_123"},
        )

    assert response.status_code == 409
    assert response.headers["x-request-id"] == "client_request_123"
    assert response.json() == {
        "code": "RESOURCE_CONFLICT",
        "message": "资源已被其他请求修改",
        "requestId": "client_request_123",
        "retryable": False,
        "details": {"field": "revision"},
    }


async def test_invalid_client_request_id_is_replaced() -> None:
    transport = ASGITransport(app=app_with_failure_route())

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/_test/conflict",
            headers={"X-Request-ID": "invalid request id with whitespace"},
        )

    request_id = response.headers["x-request-id"]
    assert request_id.startswith("req_")
    assert response.json()["requestId"] == request_id
    assert "invalid request id" not in response.text


async def test_unknown_route_uses_standard_not_found_error() -> None:
    transport = ASGITransport(app=create_app(readiness_probe=ReadyProbe()))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {
        "code": "NOT_FOUND",
        "message": "请求的资源不存在",
        "requestId": response.headers["x-request-id"],
        "retryable": False,
        "details": None,
    }


async def test_request_log_contains_trace_and_authorization_context_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    transport = ASGITransport(app=create_app(readiness_probe=ReadyProbe()))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/does-not-exist", headers={"X-Request-ID": "req_log_fields"})

    events = [
        json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")
    ]
    request_event = next(
        event for event in events if event.get("event") == "http_request_completed"
    )
    assert request_event["requestId"] == "req_log_fields"
    assert request_event["route"] == "/does-not-exist"
    assert request_event["statusCode"] == 404
    assert request_event["errorCode"] == "NOT_FOUND"
    assert request_event["userId"] is None
    assert request_event["projectId"] is None


async def test_unhandled_error_preserves_cors_standard_error_and_safe_diagnostics(
    capsys: pytest.CaptureFixture[str],
) -> None:
    transport = ASGITransport(app=app_with_unhandled_route(), raise_app_exceptions=False)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/_test/unhandled",
            headers={
                "Origin": "http://localhost:5173",
                "X-Request-ID": "req_unhandled",
            },
        )

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.json() == {
        "code": "INTERNAL_ERROR",
        "message": "服务暂时无法完成请求",
        "requestId": "req_unhandled",
        "retryable": True,
        "details": None,
    }

    output = capsys.readouterr().out
    events = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
    request_event = next(
        event for event in events if event.get("event") == "http_request_completed"
    )
    error_event = next(event for event in events if event.get("event") == "unhandled_request_error")
    assert request_event["errorCode"] == "INTERNAL_ERROR"
    assert error_event["errorStack"]
    assert "sensitive diagnostic detail" not in output
