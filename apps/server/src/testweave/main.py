from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine

from testweave.api.health import router as health_router
from testweave.api.v1 import v1_router
from testweave.api.v1.external_gateway import router as external_gateway_router
from testweave.core.config import Settings, get_settings
from testweave.core.errors import UnhandledExceptionMiddleware, register_exception_handlers
from testweave.core.logging import configure_logging
from testweave.core.readiness import (
    NotConfiguredReadinessProbe,
    ReadinessProbe,
    SqlAlchemyReadinessProbe,
)
from testweave.core.request_context import RequestContextMiddleware
from testweave.db.migrations import MIGRATIONS_PATH
from testweave.db.session import create_database_engine
from testweave.infrastructure.android_mcp.client import ReadOnlyAndroidMcpClient
from testweave.modules.android_device_monitor.service import AndroidDeviceMonitorService
from testweave.modules.android_device_monitor.stream import AndroidDeviceStreamManager


def create_app(
    settings: Settings | None = None,
    readiness_probe: ReadinessProbe | None = None,
) -> FastAPI:
    runtime_settings = settings or get_settings()
    configure_logging(runtime_settings.log_level)

    database_engine: Engine | None = None
    if readiness_probe is None:
        database_engine = create_database_engine(runtime_settings)
        if database_engine is None:
            readiness_probe = NotConfiguredReadinessProbe()
        else:
            readiness_probe = SqlAlchemyReadinessProbe(
                database_engine,
                MIGRATIONS_PATH,
            )

    android_mcp_client = ReadOnlyAndroidMcpClient(runtime_settings.android_mcp)
    if runtime_settings.android_mcp.enabled and runtime_settings.secret_key is None:
        raise ValueError("启用 Android MCP 时必须配置 TESTWEAVE_SECRET_KEY")
    android_secret = (
        runtime_settings.secret_key.get_secret_value() if runtime_settings.secret_key else ""
    )
    android_device_monitor = AndroidDeviceMonitorService(
        android_mcp_client,
        secret=android_secret,
        max_info_concurrency=runtime_settings.android_mcp.max_info_concurrency,
    )
    android_stream_settings = runtime_settings.android_mcp
    android_device_stream_manager = AndroidDeviceStreamManager(
        android_device_monitor,
        enabled=android_stream_settings.enabled and android_stream_settings.stream_enabled,
        interval_seconds=android_stream_settings.stream_interval_ms / 1000,
        idle_grace_seconds=android_stream_settings.stream_idle_grace_seconds,
        device_recheck_seconds=android_stream_settings.stream_device_recheck_seconds,
        max_backoff_seconds=android_stream_settings.stream_max_backoff_seconds,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await android_device_stream_manager.shutdown()
            await android_mcp_client.close()
            if database_engine is not None:
                database_engine.dispose()

    app = FastAPI(
        title=runtime_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs" if runtime_settings.environment != "production" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if runtime_settings.environment != "production" else None,
    )
    app.state.readiness_probe = readiness_probe
    app.state.database_engine = database_engine
    app.state.android_mcp_client = android_mcp_client
    app.state.android_device_monitor = android_device_monitor
    app.state.android_device_stream_manager = android_device_stream_manager
    app.state.allowed_websocket_origins = frozenset(runtime_settings.cors_origins)

    app.add_middleware(UnhandledExceptionMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=runtime_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "X-Request-ID", "X-CSRF-Token"],
        expose_headers=["X-Request-ID", "X-Captured-At"],
    )
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(v1_router)
    app.include_router(external_gateway_router)

    # 挂载 MCP (Model Context Protocol) 兼容端点
    @app.get("/mcp", summary="MCP Protocol Server Info")
    @app.get("/mcp/sse", summary="MCP Protocol SSE Stream")
    async def mcp_server_info() -> dict:
        return {
            "status": "active",
            "name": "TestWeave MCP Server",
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "resources": {},
                "tools": {"listChanged": True},
                "prompts": {},
            },
        }

    return app


app = create_app()
