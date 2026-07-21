from collections.abc import Mapping

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel

from testweave.core.errors import AppError, ErrorResponse
from testweave.core.readiness import ReadinessFailure, ReadinessProbe

router = APIRouter(prefix="/health", tags=["health"])
logger = structlog.get_logger(__name__)


class LiveHealthResponse(BaseModel):
    status: str


class ReadyHealthResponse(BaseModel):
    status: str
    checks: dict[str, str]


@router.get("/live", response_model=LiveHealthResponse)
def live() -> LiveHealthResponse:
    return LiveHealthResponse(status="ok")


@router.get(
    "/ready",
    response_model=ReadyHealthResponse,
    responses={503: {"model": ErrorResponse}},
)
def ready(request: Request) -> ReadyHealthResponse:
    probe: ReadinessProbe = request.app.state.readiness_probe
    try:
        checks: Mapping[str, str] = probe.check()
    except ReadinessFailure:
        logger.warning("readiness_check_failed")
        raise AppError(
            code="SERVICE_NOT_READY",
            message="服务暂未就绪，请稍后重试",
            status_code=503,
            retryable=True,
        ) from None
    return ReadyHealthResponse(status="ok", checks=dict(checks))
