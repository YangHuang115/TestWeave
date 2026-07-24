import json
from pathlib import Path
from typing import Any

from testweave.core.errors import AppError


class LocalWorkspaceGenerator:
    @staticmethod
    def generate_local_workspace(spec: dict[str, Any], output_dir: str | Path) -> list[str]:
        target_path = Path(output_dir).resolve()

        if target_path.exists() and any(target_path.iterdir()):
            raise AppError(
                code="TARGET_DIRECTORY_NOT_EMPTY",
                message=f"目标生成目录必须为空: {target_path}",
                status_code=400,
            )

        target_path.mkdir(parents=True, exist_ok=True)
        created_files: list[str] = []

        # 1. 写入 spec.json
        spec_file = target_path / "spec.json"
        spec_file.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
        created_files.append("spec.json")

        # 2. 写入 templates.files
        templates = spec.get("templates", {}).get("files", [])
        for tmpl in templates:
            rel_path = tmpl.get("path")
            content = tmpl.get("content", "")
            if not rel_path:
                continue

            file_path = (target_path / rel_path).resolve()
            # 安全越界检查
            if not str(file_path).startswith(str(target_path)):
                raise AppError(
                    code="INVALID_FILE_PATH",
                    message=f"不安全的目标文件路径: {rel_path}",
                    status_code=400,
                )

            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            created_files.append(rel_path)

        return created_files
