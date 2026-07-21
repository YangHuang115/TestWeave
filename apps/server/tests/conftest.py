from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def db() -> Generator[Session, None, None]:
    from sqlalchemy import create_engine

    from testweave.db.base import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(bind=engine)
