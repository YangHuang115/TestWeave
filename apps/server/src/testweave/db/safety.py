from ipaddress import ip_address

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class UnsafeDatabaseTarget(RuntimeError):
    """Raised before a destructive database command can reach an unsafe target."""


def _is_loopback_host(host: str | None) -> bool:
    if host is None:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def assert_disposable_test_database_url(database_url: str, *, environment: str) -> None:
    """Fail closed unless a destructive test targets a local, dedicated test database."""

    if environment != "test":
        raise UnsafeDatabaseTarget("破坏性数据库测试仅允许在 test 环境运行")

    try:
        target = make_url(database_url)
    except ArgumentError:
        raise UnsafeDatabaseTarget("数据库测试目标不是有效连接串") from None

    if target.drivername != "postgresql+psycopg":
        raise UnsafeDatabaseTarget("数据库测试目标必须显式使用 psycopg 驱动")
    if target.query:
        raise UnsafeDatabaseTarget("破坏性数据库测试连接串不允许 query 参数")
    if not _is_loopback_host(target.host):
        raise UnsafeDatabaseTarget("破坏性数据库测试仅允许连接本机数据库")
    if target.database is None or not target.database.endswith("_test"):
        raise UnsafeDatabaseTarget("数据库测试目标名称必须以 _test 结尾")
