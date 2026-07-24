import io
import zipfile
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from testweave.modules.projects.service import ProjectService
from testweave.modules.requirements.service import RequirementService
from testweave.modules.users.service import UserService
from testweave.modules.versions.service import VersionService

pytestmark = pytest.mark.integration


@pytest.fixture
async def att_integration_context(client: AsyncClient, session: Session) -> dict[str, Any]:
    admin_user = UserService.create_user(
        session,
        username="attapiadmin",
        email="ata@tw.com",
        display_name="Att API Admin",
        password="pwd",
    )
    UserService.create_user(
        session,
        username="attapiguest",
        email="atg@tw.com",
        display_name="Att API Guest",
        password="pwd",
    )
    session.commit()

    project = ProjectService.create_project(
        session, key="ATTAPIP", name="Att API Project", owner_id=admin_user.id, request_id="att-p"
    )
    session.commit()

    VersionService.create_version(
        session,
        project_id=project.id,
        key="v1.0",
        name="API Version 1.0",
        owner_id=admin_user.id,
        actor_id=admin_user.id,
        request_id="att-v",
    )
    session.commit()

    req = RequirementService.create_requirement(
        session,
        project_id=project.id,
        requirement_no="REQ-3001",
        title="API requirement",
        description="Integration test requirement",
        priority="HIGH",
        owner_id=admin_user.id,
        actor_id=admin_user.id,
        request_id="att-r",
    )
    session.commit()

    # 登录并获取 cookies 与 csrf 令牌
    res_admin = await client.post(
        "/api/v1/auth/login", json={"username_or_email": "attapiadmin", "password": "pwd"}
    )
    cookies_admin = res_admin.cookies
    csrf_admin = cookies_admin.get("xsrf_token")

    res_guest = await client.post(
        "/api/v1/auth/login", json={"username_or_email": "attapiguest", "password": "pwd"}
    )
    cookies_guest = res_guest.cookies
    csrf_guest = cookies_guest.get("xsrf_token")

    return {
        "project": project,
        "requirement": req,
        "admin_session": {"cookies": cookies_admin, "headers": {"X-CSRF-Token": csrf_admin}},
        "guest_session": {"cookies": cookies_guest, "headers": {"X-CSRF-Token": csrf_guest}},
    }


def create_valid_docx_bytes() -> bytes:
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:
        zf.writestr("word/document.xml", "<w:document></w:document>")
    return bio.getvalue()


@pytest.mark.anyio
async def test_attachment_api_lifecycle(
    client: AsyncClient, session: Session, att_integration_context: dict[str, Any]
) -> None:
    project = att_integration_context["project"]
    req = att_integration_context["requirement"]
    admin_session = att_integration_context["admin_session"]
    guest_session = att_integration_context["guest_session"]

    docx_bytes = create_valid_docx_bytes()

    # 1. 管理员成功上传附件 (POST)
    # httpx files 接收 tuple: (filename, file_bytes, content_type)
    files = {
        "file": (
            "测试文档.docx",
            docx_bytes,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }
    res_upload = await client.post(
        f"/api/v1/projects/{project.id}/requirements/{req.id}/attachments",
        files=files,
        **admin_session,
    )
    assert res_upload.status_code == 201
    att_data = res_upload.json()
    assert att_data["original_filename"] == "测试文档.docx"
    att_id = att_data["id"]

    # 2. 隔离越权测试：非项目成员列出附件和下载附件，均应返回 403
    res_guest_list = await client.get(
        f"/api/v1/projects/{project.id}/requirements/{req.id}/attachments",
        **guest_session,
    )
    assert res_guest_list.status_code == 403

    res_guest_download = await client.get(
        f"/api/v1/projects/{project.id}/requirements/{req.id}/attachments/{att_id}",
        **guest_session,
    )
    assert res_guest_download.status_code == 403

    # 3. 列表获取测试：管理员获取列表
    res_list = await client.get(
        f"/api/v1/projects/{project.id}/requirements/{req.id}/attachments",
        **admin_session,
    )
    assert res_list.status_code == 200
    assert len(res_list.json()) == 1
    assert res_list.json()[0]["id"] == att_id

    # 4. 下载测试：管理员下载，验证流及文件名 header
    res_download = await client.get(
        f"/api/v1/projects/{project.id}/requirements/{req.id}/attachments/{att_id}",
        **admin_session,
    )
    assert res_download.status_code == 200
    assert res_download.content == docx_bytes
    # 验证 Content-Disposition 支持安全文件名编码
    disposition = res_download.headers.get("Content-Disposition")
    assert disposition is not None
    assert "filename*=UTF-8''" in disposition

    # 5. 归档删除测试：管理员删除
    res_delete = await client.delete(
        f"/api/v1/projects/{project.id}/requirements/{req.id}/attachments/{att_id}",
        **admin_session,
    )
    assert res_delete.status_code == 204

    # 再次列表应该为空
    res_list_after = await client.get(
        f"/api/v1/projects/{project.id}/requirements/{req.id}/attachments",
        **admin_session,
    )
    assert len(res_list_after.json()) == 0
