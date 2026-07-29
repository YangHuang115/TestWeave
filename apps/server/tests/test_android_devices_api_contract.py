from fastapi import FastAPI
from fastapi.routing import APIWebSocketRoute

from testweave.api.v1.android_devices import router


def test_android_screen_openapi_declares_png_response() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    response = app.openapi()["paths"][
        "/api/v1/projects/{projectId}/android-devices/{deviceRef}/screen"
    ]["get"]["responses"]["200"]

    assert response["content"]["image/png"] == {}


def test_android_stream_route_is_registered_as_websocket() -> None:
    route = next(
        route
        for route in router.routes
        if getattr(route, "path", "") == "/projects/{projectId}/android-devices/{deviceRef}/stream"
    )

    assert isinstance(route, APIWebSocketRoute)
