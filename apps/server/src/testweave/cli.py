import argparse
import getpass
import sys

from sqlalchemy.orm import Session

from testweave.core.config import get_settings
from testweave.db.session import create_database_engine
from testweave.modules.users.service import UserService


def create_admin(username: str, email: str, display_name: str) -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    if engine is None:
        print("错误: 无法根据配置初始化数据库 Engine")
        sys.exit(1)

    print("--- 初始化系统管理员账号 ---")
    password = getpass.getpass("请输入管理员密码: ")
    if not password:
        print("错误: 密码不能为空")
        sys.exit(1)

    confirm_password = getpass.getpass("请再次确认密码: ")
    if password != confirm_password:
        print("错误: 两次输入的密码不一致")
        sys.exit(1)

    with Session(engine) as db:
        try:
            user = UserService.create_user(
                db,
                username=username,
                email=email,
                display_name=display_name,
                password=password,
                is_system_admin=True,
            )
            db.commit()
            print(f"成功: 系统管理员账号创建成功! ID: {user.id}, 用户名: {user.username}")
        except ValueError as e:
            db.rollback()
            print(f"冲突错误: {e}")
            sys.exit(1)
        except Exception as e:
            db.rollback()
            print(f"未知错误: {e}")
            sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="TestWeave 命令行管理工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # create-admin 子命令
    admin_parser = subparsers.add_parser("create-admin", help="初始化创建系统管理员")
    admin_parser.add_argument("--username", required=True, help="用户名")
    admin_parser.add_argument("--email", required=True, help="电子邮箱")
    admin_parser.add_argument("--display-name", required=True, help="显示姓名")

    args = parser.parse_args()

    if args.command == "create-admin":
        create_admin(args.username, args.email, args.display_name)


if __name__ == "__main__":
    main()
