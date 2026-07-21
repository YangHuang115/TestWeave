import os
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from testweave.api.dependencies.database import get_db
from testweave.core.config import get_settings
from testweave.db.safety import assert_disposable_test_database_url
from testweave.main import create_app

SERVER_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG_PATH = SERVER_ROOT / "alembic.ini"


@pytest.fixture(scope="module")
def setup_integration_db() -> Generator[Any, None, None]:
    database_url = os.getenv("TESTWEAVE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("需要通过 TESTWEAVE_TEST_DATABASE_URL 指定一次性 PostgreSQL 测试库")

    assert_disposable_test_database_url(
        database_url,
        environment=os.getenv("TESTWEAVE_ENVIRONMENT", ""),
    )

    os.environ["TESTWEAVE_DATABASE_URL"] = database_url
    # 集成测试需要可销毁测试库与测试用加密主密钥；生产环境由强密钥校验保证，这里不提供生产默认值。
    os.environ.setdefault(
        "TESTWEAVE_SECRET_KEY",
        "test-only-disposable-secret-key-not-for-prod-0123456789",
    )
    get_settings.cache_clear()

    config = Config(str(ALEMBIC_CONFIG_PATH))
    command.upgrade(config, "head")

    engine = create_engine(database_url)

    yield engine
    engine.dispose()


@pytest.fixture
def session(setup_integration_db: Any) -> Generator[Session, None, None]:
    engine = setup_integration_db
    connection = engine.connect()
    transaction = connection.begin()
    s = Session(bind=connection)

    # 将 commit 改为 flush，将 rollback 改为 no-op，确保在整个测试运行中，
    # 即使 API 触发了异常回滚或提交，测试数据也不会丢失，最终由连接级事务统一回滚
    s.commit = s.flush  # type: ignore[assignment]
    s.rollback = lambda: None  # type: ignore[assignment]

    yield s
    s.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def test_app(setup_integration_db: Any) -> FastAPI:
    settings = get_settings()
    app = create_app(settings=settings)
    app.state.database_engine = setup_integration_db
    return app


@pytest.fixture
def client(test_app: FastAPI, session: Session) -> Generator[AsyncClient, None, None]:
    # 覆盖 get_db 依赖，返回当前用例的 Session，确保 API 请求与测试处于同一事务中，具备即时可见性
    test_app.dependency_overrides[get_db] = lambda: session
    transport = ASGITransport(app=test_app)

    # 规避 DeprecationWarning，但在测试中可以继续使用 AsyncClient
    c = AsyncClient(transport=transport, base_url="http://test")
    yield c

    # 用例结束清除重写，保持干净
    test_app.dependency_overrides.clear()
