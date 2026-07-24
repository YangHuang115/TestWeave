import io
import zipfile

import pytest
from fastapi import UploadFile
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.modules.attachments.service import AttachmentService
from testweave.modules.projects.service import ProjectService
from testweave.modules.requirements.service import RequirementService
from testweave.modules.users.service import UserService
from testweave.modules.versions.service import VersionService


@pytest.fixture
def attachment_test_context(db: Session) -> dict:
    user = UserService.create_user(
        db,
        username="attester",
        email="att@testweave.com",
        display_name="Attachment Tester",
        password="pwd",
    )
    db.commit()

    project = ProjectService.create_project(
        db,
        key="ATTPROJ",
        name="Attachment Project",
        owner_id=user.id,
        request_id="att-p",
    )
    db.commit()

    version = VersionService.create_version(
        db,
        project_id=project.id,
        key="v1.0",
        name="Version 1.0",
        owner_id=user.id,
        actor_id=user.id,
        request_id="att-v",
    )
    db.commit()

    req = RequirementService.create_requirement(
        db,
        project_id=project.id,
        requirement_no="REQ-1001",
        title="Test Requirement",
        description=None,
        priority="LOW",
        owner_id=user.id,
        actor_id=user.id,
        request_id="att-r",
    )
    db.commit()

    return {"user": user, "project": project, "version": version, "requirement": req}


def create_mock_docx(vba: bool = False, file_count: int = 1, zip_bomb: bool = False) -> bytes:
    """动态在内存中生成各种测试用的 ZIP/DOCX 字节包"""
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:
        if file_count > 100:
            for i in range(file_count):
                zf.writestr(f"item_{i}.txt", "content")
        elif zip_bomb:
            zf.writestr("word/document.xml", "<w:document></w:document>")
            zf.writestr(
                "huge.txt", b"\x00" * (1024 * 1024 * 10), compress_type=zipfile.ZIP_DEFLATED
            )
        else:
            zf.writestr("word/document.xml", "<w:document></w:document>")
            if vba:
                zf.writestr("word/vbaProject.bin", "malicious_macro_vba")
    return bio.getvalue()


@pytest.mark.anyio
async def test_upload_attachment_docx_safety_filter(
    db: Session, attachment_test_context: dict
) -> None:
    user = attachment_test_context["user"]
    project = attachment_test_context["project"]
    req = attachment_test_context["requirement"]

    # 1. 拦截非 docx 后缀
    non_docx = UploadFile(file=io.BytesIO(b"abc"), filename="test.pdf")
    with pytest.raises(AppError) as exc_info:
        await AttachmentService.upload_attachment(
            db, str(project.id), str(req.id), non_docx, str(user.id), "req-u1"
        )
    assert exc_info.value.code == "INVALID_FILE_TYPE"

    # 2. 拦截非 ZIP 魔术头文件
    fake_docx = UploadFile(file=io.BytesIO(b"This is a fake text file"), filename="fake.docx")
    with pytest.raises(AppError) as exc_info:
        await AttachmentService.upload_attachment(
            db, str(project.id), str(req.id), fake_docx, str(user.id), "req-u2"
        )
    assert exc_info.value.code == "INVALID_FILE_TYPE"

    # 3. 拦截含有 VBA 宏的 DOCX
    vba_bytes = create_mock_docx(vba=True)
    vba_docx = UploadFile(file=io.BytesIO(vba_bytes), filename="vba.docx")
    with pytest.raises(AppError) as exc_info:
        await AttachmentService.upload_attachment(
            db, str(project.id), str(req.id), vba_docx, str(user.id), "req-u3"
        )
    assert exc_info.value.code == "FILE_SAFETY_VIOLATION"
    assert "宏(VBA)" in exc_info.value.message

    # 4. 拦截条目数过多的 ZIP
    many_files_bytes = create_mock_docx(file_count=101)
    many_docx = UploadFile(file=io.BytesIO(many_files_bytes), filename="many.docx")
    with pytest.raises(AppError) as exc_info:
        await AttachmentService.upload_attachment(
            db, str(project.id), str(req.id), many_docx, str(user.id), "req-u4"
        )
    assert exc_info.value.code == "FILE_SAFETY_VIOLATION"
    assert "文件条目过多" in exc_info.value.message

    # 5. 拦截压缩比率超标的文件 (ZIP Bomb)
    bomb_bytes = create_mock_docx(zip_bomb=True)
    bomb_docx = UploadFile(file=io.BytesIO(bomb_bytes), filename="bomb.docx")
    with pytest.raises(AppError) as exc_info:
        await AttachmentService.upload_attachment(
            db, str(project.id), str(req.id), bomb_docx, str(user.id), "req-u5"
        )
    assert exc_info.value.code == "FILE_SAFETY_VIOLATION"
    assert "解压比率异常过高" in exc_info.value.message or "有效的 Word" in exc_info.value.message

    # 6. 成功上传合规 docx
    valid_bytes = create_mock_docx()
    valid_docx = UploadFile(file=io.BytesIO(valid_bytes), filename="支付宝对接.docx")
    att = await AttachmentService.upload_attachment(
        db, str(project.id), str(req.id), valid_docx, str(user.id), "req-u6"
    )
    db.commit()

    assert att.id is not None
    assert att.original_filename == "支付宝对接.docx"
    assert att.status == "ACTIVE"
    assert att.size_bytes == len(valid_bytes)


@pytest.mark.anyio
async def test_attachment_lifecycle_list_download_archive(
    db: Session, attachment_test_context: dict
) -> None:
    user = attachment_test_context["user"]
    project = attachment_test_context["project"]
    req = attachment_test_context["requirement"]

    # 上传附件
    valid_bytes = create_mock_docx()
    valid_docx = UploadFile(file=io.BytesIO(valid_bytes), filename="doc.docx")
    att = await AttachmentService.upload_attachment(
        db, str(project.id), str(req.id), valid_docx, str(user.id), "req-a1"
    )
    db.commit()

    # 1. 列表获取
    lst = AttachmentService.list_attachments(db, str(project.id), str(req.id))
    assert len(lst) == 1
    assert lst[0].id == att.id

    # 2. 正常下载
    stream, filename, content_type = await AttachmentService.get_attachment_stream(
        db, str(project.id), str(req.id), str(att.id), str(user.id), "req-d1"
    )
    assert filename == "doc.docx"
    assert content_type is not None
    # 消费流以验证内容完整性
    content = b""
    async for chunk in stream:
        content += chunk
    assert content == valid_bytes

    # 3. 归档软删除
    AttachmentService.archive_attachment(
        db, str(project.id), str(req.id), str(att.id), str(user.id), "req-del"
    )
    db.commit()

    # 列表应该为空
    assert len(AttachmentService.list_attachments(db, str(project.id), str(req.id))) == 0

    # 归档后下载应该被拦截 (返回 400 ATTACHMENT_ARCHIVED)
    with pytest.raises(AppError) as exc_info:
        await AttachmentService.get_attachment_stream(
            db, str(project.id), str(req.id), str(att.id), str(user.id), "req-d2"
        )
    assert exc_info.value.code == "ATTACHMENT_ARCHIVED"
