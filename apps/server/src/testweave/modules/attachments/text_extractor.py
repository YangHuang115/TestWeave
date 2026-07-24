import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from testweave.core.config import get_settings
from testweave.infrastructure.storage import LocalStorageProvider


def extract_attachment_text(storage_key: str, max_chars: int = 100_000) -> str | None:
    """从已通过上传安全校验的本地附件提取有界文本。"""
    try:
        settings = get_settings()
        storage = LocalStorageProvider(settings.storage_local_dir)
        full_path = Path(storage._get_filepath(storage_key))
        if not full_path.exists():
            return None

        lower_key = storage_key.lower()
        if lower_key.endswith(".docx"):
            with zipfile.ZipFile(full_path, "r") as archive:
                if "word/document.xml" not in archive.namelist():
                    return None
                tree = ET.fromstring(archive.read("word/document.xml"))
                paragraphs = []
                consumed = 0
                for element in tree.iter():
                    if not element.tag.endswith("}p"):
                        continue
                    text = "".join(
                        child.text or "" for child in element.iter() if child.tag.endswith("}t")
                    )
                    if not text:
                        continue
                    remaining = max_chars - consumed
                    if remaining <= 0:
                        break
                    paragraphs.append(text[:remaining])
                    consumed += len(paragraphs[-1]) + 1
                extracted = "\n".join(paragraphs).strip()
                return extracted or None

        if any(
            lower_key.endswith(extension)
            for extension in (".txt", ".md", ".json", ".yaml", ".yml", ".csv")
        ):
            extracted = full_path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
            return extracted.strip() or None
    except (OSError, ValueError, zipfile.BadZipFile, ET.ParseError):
        return None
    return None
