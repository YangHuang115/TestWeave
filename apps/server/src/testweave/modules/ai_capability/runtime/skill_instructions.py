from typing import Any


def resolve_skill_instructions(
    package_files: dict[str, Any],
    skill_name: str,
) -> str:
    """优先读取可独立编辑的 prompt.md，并兼容历史 SKILL.md 快照。"""

    candidates = []
    if skill_name:
        candidates.extend(
            [
                f"skills/{skill_name}/prompt.md",
                f"skills/{skill_name}/SKILL.md",
            ]
        )
    candidates.extend(["prompt.md", "SKILL.md"])

    for path in candidates:
        content = package_files.get(path)
        if isinstance(content, str) and content.strip():
            return content
    return "You are an AI assistant."
