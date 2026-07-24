import uuid
from datetime import UTC, datetime
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from testweave.api.dependencies.auth import get_current_user
from testweave.api.dependencies.database import get_db
from testweave.db.base import Base
from testweave.db.models import Project, ProjectMember, Requirement, User
from testweave.main import app


@pytest.fixture
def workbench_api_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        yield session, engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_workbench_api_endpoints_and_isolation(workbench_api_db):
    db, engine = workbench_api_db

    # 1. 创建 2 个用户
    user_owner = User(
        id=uuid.uuid4(),
        username="owner_user",
        email="owner@test.com",
        display_name="Owner User",
        hashed_password="hash",
    )
    user_other = User(
        id=uuid.uuid4(),
        username="other_user",
        email="other@test.com",
        display_name="Other User",
        hashed_password="hash",
    )
    db.add_all([user_owner, user_other])
    db.flush()

    # 2. 创建 2 个项目
    proj_a = Project(
        id=uuid.uuid4(),
        name="Project A",
        key="PA",
        owner_id=user_owner.id,
    )
    proj_b = Project(
        id=uuid.uuid4(),
        name="Project B",
        key="PB",
        owner_id=user_other.id,
    )
    db.add_all([proj_a, proj_b])
    db.flush()

    # 成员关系
    db.add_all(
        [
            ProjectMember(project_id=proj_a.id, user_id=user_owner.id, role_id="project_admin"),
            ProjectMember(project_id=proj_b.id, user_id=user_other.id, role_id="project_admin"),
        ]
    )
    db.flush()

    # 3. 为 user_owner 创建 1 个需求
    req = Requirement(
        id=uuid.uuid4(),
        project_id=proj_a.id,
        requirement_no="REQ-999",
        requirement_no_normalized="req-999",
        title="API Test Requirement",
        priority="HIGH",
        status="DRAFT",
        owner_id=user_owner.id,
    )
    db.add(req)
    db.commit()

    app.state.database_engine = engine
    app.dependency_overrides[get_current_user] = lambda: user_owner

    client = TestClient(app)

    try:
        # 1. GET Summary
        resp = client.get(f"/api/v1/projects/{proj_a.id}/workbench/summary")
        assert resp.status_code == 200, f"Error: {resp.text}"
        data = resp.json()
        assert data["remaining_requirements_count"] == 1
        assert data["my_todos_count"] == 1
        assert data["in_progress_tasks_count"] == 0
        assert data["waiting_human_count"] == 0

        # 2. GET Todos
        resp_todos = client.get(f"/api/v1/projects/{proj_a.id}/workbench/todos")
        assert resp_todos.status_code == 200
        todos_data = resp_todos.json()
        assert todos_data["total"] == 1
        assert todos_data["items"][0]["type"] == "REQUIREMENT_DESIGN"
        assert todos_data["items"][0]["target_id"] == str(req.id)

        # 3. POST Recent Visit & GET Recent Visit
        resp_post_visit = client.post(
            f"/api/v1/projects/{proj_a.id}/workbench/recent-visits",
            json={"resource_type": "requirement", "resource_id": str(req.id)},
        )
        assert resp_post_visit.status_code == 201
        visit_data = resp_post_visit.json()
        assert visit_data["resource_type"] == "requirement"
        assert visit_data["resource_id"] == str(req.id)
        assert "REQ-999" in visit_data["title"]

        resp_visits = client.get(f"/api/v1/projects/{proj_a.id}/workbench/recent-visits")
        assert resp_visits.status_code == 200
        assert resp_visits.json()["total"] == 1

        # 4. 项目权限隔离测试：访问无权限的项目 proj_b
        resp_isolation = client.get(f"/api/v1/projects/{proj_b.id}/workbench/summary")
        assert resp_isolation.status_code in (403, 404)
    finally:
        app.dependency_overrides.clear()
