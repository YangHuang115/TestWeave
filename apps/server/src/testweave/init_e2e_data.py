import sys

from sqlalchemy.orm import Session

from testweave.core.config import get_settings
from testweave.core.security import hash_password
from testweave.db.models import User
from testweave.db.session import create_database_engine


def run() -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    if engine is None:
        print("Error: Could not create database engine")
        sys.exit(1)

    with Session(engine) as db:
        try:
            # 1. 幂等更新或创建 E2E 系统管理员
            admin = db.query(User).filter(User.email == "admin@e2e.com").first()
            if admin:
                admin.is_system_admin = True
                admin.hashed_password = hash_password("1")
                print(f"Updated existing admin user: {admin.id}")
            else:
                admin = User(
                    username="e2e_admin",
                    email="admin@e2e.com",
                    display_name="E2E Admin User",
                    hashed_password=hash_password("1"),
                    is_system_admin=True,
                    status="active",
                )
                db.add(admin)
                db.flush()
                print(f"Created new e2e_admin: {admin.id}")

            # 2. 幂等更新或创建 E2E 普通无项目用户
            normal = db.query(User).filter(User.email == "normal@e2e.com").first()
            if normal:
                normal.is_system_admin = False
                normal.hashed_password = hash_password("1")
                print(f"Updated existing normal user: {normal.id}")
            else:
                normal = User(
                    username="e2e_normal",
                    email="normal@e2e.com",
                    display_name="E2E Normal User",
                    hashed_password=hash_password("1"),
                    is_system_admin=False,
                    status="active",
                )
                db.add(normal)
                db.flush()
                print(f"Created new e2e_normal: {normal.id}")

            # 3. 幂等更新或创建 E2E 普通受限用户一 (将被添加至项目A)
            member_a = db.query(User).filter(User.email == "member_a@e2e.com").first()
            if member_a:
                member_a.is_system_admin = False
                member_a.hashed_password = hash_password("1")
                print(f"Updated existing member_a user: {member_a.id}")
            else:
                member_a = User(
                    username="e2e_member_a",
                    email="member_a@e2e.com",
                    display_name="Member A User",
                    hashed_password=hash_password("1"),
                    is_system_admin=False,
                    status="active",
                )
                db.add(member_a)
                db.flush()
                print(f"Created new e2e_member_a: {member_a.id}")

            # 4. 幂等更新或创建 E2E 普通受限用户二 (将被添加至项目B)
            member_b = db.query(User).filter(User.email == "member_b@e2e.com").first()
            if member_b:
                member_b.is_system_admin = False
                member_b.hashed_password = hash_password("1")
                print(f"Updated existing member_b user: {member_b.id}")
            else:
                member_b = User(
                    username="e2e_member_b",
                    email="member_b@e2e.com",
                    display_name="Member B User",
                    hashed_password=hash_password("1"),
                    is_system_admin=False,
                    status="active",
                )
                db.add(member_b)
                db.flush()
                print(f"Created new e2e_member_b: {member_b.id}")

            db.commit()
            print("E2E database mock users initialized successfully (Idempotent).")
        except Exception as e:
            db.rollback()
            print(f"Database setup error: {e}")
            sys.exit(1)


if __name__ == "__main__":
    run()
