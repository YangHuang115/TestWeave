from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine

from testweave.api.health import router as health_router
from testweave.api.v1 import v1_router
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

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
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

    app.add_middleware(UnhandledExceptionMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=runtime_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "X-Request-ID", "X-CSRF-Token"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(v1_router)
    return app


app = create_app()
