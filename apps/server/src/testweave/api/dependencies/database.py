from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session


def get_db(request: Request) -> Generator[Session, None, None]:
    """从 FastAPI app.state 动态获取数据库 Engine 并返回 SQLAlchemy Session"""
    engine = getattr(request.app.state, "database_engine", None)
    if engine is None:
        raise RuntimeError("FastAPI state 中未初始化 database_engine")

    # 使用 context manager 确保 Session 正确关闭与回滚
    with Session(engine) as session:
        yield session
