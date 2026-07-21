import traceback
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from testweave.core.request_context import get_request_id

logger = structlog.get_logger(__name__)


class ErrorResponse(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    code: str
    message: str
    request_id: str = Field(serialization_alias="requestId")
    retryable: bool = False
    details: Any | None = None


class AppError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
        retryable: bool = False,
        details: Any | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.details = details


ExceptionHandler = Callable[[Request, Exception], Awaitable[JSONResponse]]


def _response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    retryable: bool = False,
    details: Any | None = None,
) -> JSONResponse:
    request_id = get_request_id(request)
    request.state.error_code = code
    body = ErrorResponse(
        code=code,
        message=message,
        request_id=request_id,
        retryable=retryable,
        details=details,
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json", by_alias=True),
        headers={"X-Request-ID": request_id},
    )


async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    return _response(
        request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        retryable=exc.retryable,
        details=exc.details,
    )


async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code == 404:
        return _response(
            request,
            status_code=404,
            code="NOT_FOUND",
            message="请求的资源不存在",
        )
    return _response(
        request,
        status_code=exc.status_code,
        code="HTTP_ERROR",
        message="请求无法完成",
    )


async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {
            "location": ".".join(str(part) for part in error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        }
        for error in exc.errors()
    ]
    return _response(
        request,
        status_code=422,
        code="VALIDATION_ERROR",
        message="请求参数不符合要求",
        details=details,
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    error_stack = [
        {
            "file": Path(frame.filename).name,
            "line": frame.lineno,
            "function": frame.name,
        }
        for frame in traceback.extract_tb(exc.__traceback__)[-20:]
    ]
    logger.error(
        "unhandled_request_error",
        requestId=get_request_id(request),
        errorType=type(exc).__name__,
        errorStack=error_stack,
    )
    return _response(
        request,
        status_code=500,
        code="INTERNAL_ERROR",
        message="服务暂时无法完成请求",
        retryable=True,
    )


class UnhandledExceptionMiddleware:
    """Convert unexpected endpoint failures before CORS and request logging unwind."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_with_tracking(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_with_tracking)
        except Exception as exc:
            if response_started:
                raise
            request = Request(scope)
            response = await handle_unexpected_error(request, exc)
            await response(scope, receive, send)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, handle_app_error)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, handle_http_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, handle_validation_error)  # type: ignore[arg-type]
