import re
import time
from contextvars import ContextVar, Token
from uuid import uuid4

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

logger = structlog.get_logger(__name__)


def _new_request_id() -> str:
    return f"req_{uuid4().hex}"


def select_request_id(candidate: str | None) -> str:
    if candidate is not None and _REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return _new_request_id()


def get_request_id(request: Request | None = None) -> str:
    if request is not None:
        state_request_id = getattr(request.state, "request_id", None)
        if isinstance(state_request_id, str):
            return state_request_id
    return _request_id.get() or _new_request_id()


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = select_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        token: Token[str | None] = _request_id.set(request_id)
        structlog.contextvars.bind_contextvars(requestId=request_id)
        started = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            route = getattr(request.scope.get("route"), "path", request.url.path)
            logger.info(
                "http_request_completed",
                method=request.method,
                route=route,
                statusCode=response.status_code if response is not None else 500,
                durationMs=duration_ms,
                userId=getattr(request.state, "user_id", None),
                projectId=getattr(request.state, "project_id", None),
                errorCode=getattr(request.state, "error_code", None),
            )
            structlog.contextvars.clear_contextvars()
            _request_id.reset(token)
