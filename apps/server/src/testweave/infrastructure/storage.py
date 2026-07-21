import os
import zipfile
from abc import ABC, abstractmethod
from typing import AsyncIterator
import anyio

from testweave.core.errors import AppError


class StorageProvider(ABC):
    @abstractmethod
    async def save(self, storage_key: str, data: AsyncIterator[bytes]) -> int:
        """流式保存文件"""
        pass

    @abstractmethod
    async def get(self, storage_key: str) -> AsyncIterator[bytes]:
        """获取文件流"""
        pass

    @abstractmethod
    async def delete(self, storage_key: str) -> None:
        """删除文件"""
        pass


class LocalStorageProvider(StorageProvider):
    def __init__(self, base_dir: str):
        self.base_dir = os.path.abspath(base_dir)

    def _get_filepath(self, storage_key: str) -> str:
        # 防止目录穿越 (Path Traversal)
        normalized_key = os.path.normpath(storage_key)
        if normalized_key.startswith("..") or os.path.isabs(normalized_key):
            raise AppError(code="PATH_TRAVERSAL_DETECTED", message="非法的文件存储路径", status_code=400)
        return os.path.join(self.base_dir, normalized_key)

    async def save(self, storage_key: str, data: AsyncIterator[bytes]) -> int:
        filepath = self._get_filepath(storage_key)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        written_bytes = 0
        async with await anyio.open_file(filepath, "wb") as f:
            async for chunk in data:
                await f.write(chunk)
                written_bytes += len(chunk)
        return written_bytes

    async def get(self, storage_key: str) -> AsyncIterator[bytes]:
        filepath = self._get_filepath(storage_key)
        if not os.path.exists(filepath):
            raise AppError(code="FILE_NOT_FOUND", message="文件不存在", status_code=404)

        async def file_sender() -> AsyncIterator[bytes]:
            async with await anyio.open_file(filepath, "rb") as f:
                while True:
                    chunk = await f.read(64 * 1024) # 64KB chunk
                    if not chunk:
                        break
                    yield chunk

        return file_sender()

    async def delete(self, storage_key: str) -> None:
        filepath = self._get_filepath(storage_key)
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError as e:
                raise AppError(code="STORAGE_DELETE_FAILED", message=f"物理文件删除失败: {str(e)}", status_code=500)


class DocxSafetyFilter:
    @staticmethod
    def validate(filepath: str) -> None:
        if not os.path.exists(filepath):
            raise AppError(code="FILE_NOT_FOUND", message="待校验文件不存在", status_code=400)

        # 1. 魔术字节校验
        with open(filepath, "rb") as f:
            header = f.read(4)
            if header != b"PK\x03\x04":
                raise AppError(code="INVALID_FILE_TYPE", message="文件不是合规的 ZIP/DOCX 压缩包格式", status_code=400)

        # 2. ZIP/DOCX 内部校验
        try:
            with zipfile.ZipFile(filepath, "r") as zf:
                infolist = zf.infolist()
                
                # 防 ZIP 膨胀炸弹
                if len(infolist) > 100:
                    raise AppError(code="FILE_SAFETY_VIOLATION", message="压缩包内文件条目过多，可能存在安全风险", status_code=400)

                total_uncompressed_size = 0
                total_compressed_size = 0
                has_document_xml = False

                for info in infolist:
                    # 拦截 VBA 宏
                    if info.filename.endswith("vbaProject.bin") or "vbaProject" in info.filename:
                        raise AppError(code="FILE_SAFETY_VIOLATION", message="文档中包含宏(VBA)脚本，已被系统拒绝", status_code=400)

                    if info.filename == "word/document.xml":
                        has_document_xml = True

                    # 拦截单个文件过大
                    if info.file_size > 100 * 1024 * 1024:  # 100MB
                        raise AppError(code="FILE_SAFETY_VIOLATION", message="压缩包内单个解压文件过大，存在安全风险", status_code=400)

                    total_uncompressed_size += info.file_size
                    total_compressed_size += info.compress_size

                if not has_document_xml:
                    raise AppError(code="INVALID_FILE_TYPE", message="不是有效的 Word (.docx) 格式文档", status_code=400)

                if total_compressed_size > 0:
                    ratio = total_uncompressed_size / total_compressed_size
                    if ratio > 100.0:
                        raise AppError(code="FILE_SAFETY_VIOLATION", message="文件解压比率异常过高，可能为压缩炸弹", status_code=400)
        except zipfile.BadZipFile:
            raise AppError(code="INVALID_FILE_TYPE", message="文件内容已损坏或不是有效的 ZIP/DOCX 压缩格式", status_code=400)
