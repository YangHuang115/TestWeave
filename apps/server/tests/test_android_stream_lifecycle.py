from fastapi.testclient import TestClient

from testweave.main import create_app


class ReadyProbe:
    def check(self) -> dict[str, str]:
        return {"database": "ok"}


def test_application_shutdown_closes_android_stream_manager(monkeypatch) -> None:
    class FakeStreamManager:
        def __init__(self, *_args, **_kwargs) -> None:
            self.shutdown_calls = 0

        async def shutdown(self) -> None:
            self.shutdown_calls += 1

    manager = FakeStreamManager()
    monkeypatch.setattr(
        "testweave.main.AndroidDeviceStreamManager",
        lambda *_args, **_kwargs: manager,
    )
    app = create_app(readiness_probe=ReadyProbe())

    with TestClient(app):
        assert app.state.android_device_stream_manager is manager

    assert manager.shutdown_calls == 1
