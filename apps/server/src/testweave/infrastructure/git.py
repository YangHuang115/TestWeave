import os
import tempfile
import subprocess
import re
from urllib.parse import urlparse
import structlog

from testweave.core.errors import AppError

logger = structlog.get_logger()


class GitClient:
    @staticmethod
    def _mask_sensitive(text: str) -> str:
        if not text:
            return ""
        # 过滤 HTTP Token: https://x-token-auth:TOKEN@github.com
        text = re.sub(r"(https?://)([^:]+):([^@]+)(@)", r"\1\2:***\4", text)
        # 过滤 SSH 私钥明文
        text = re.sub(
            r"-----BEGIN [A-Z ]+ PRIVATE KEY-----[\s\S]+-----END [A-Z ]+ PRIVATE KEY-----",
            "[PRIVATE KEY MASKED]",
            text,
        )
        return text

    @classmethod
    def run_git_command(
        cls,
        args: list[str],
        auth_type: str = "NONE",
        credential_content: str | None = None,
        timeout: int = 30,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        temp_ssh_path = None

        try:
            if auth_type == "SSH_KEY" and credential_content:
                # 创建临时 SSH 私钥文件
                f = tempfile.NamedTemporaryFile(
                    mode="w", delete=False, suffix="_id_rsa", newline=""
                )
                f.write(credential_content.strip() + "\n")
                f.close()
                temp_ssh_path = f.name
                os.chmod(temp_ssh_path, 0o600)
                # 注入 GIT_SSH_COMMAND
                env["GIT_SSH_COMMAND"] = (
                    f"ssh -i {temp_ssh_path} -o StrictHostKeyChecking=no "
                    f"-o UserKnownHostsFile=/dev/null -o IdentitiesOnly=yes"
                )

            res = subprocess.run(
                args,
                capture_output=True,
                text=True,
                env=env,
                timeout=timeout,
            )

            masked_stderr = cls._mask_sensitive(res.stderr)

            if res.returncode != 0:
                try:
                    logger.warning(
                        "Git 命令执行失败",
                        args=args,
                        returncode=res.returncode,
                        stderr=masked_stderr,
                    )
                except Exception:
                    pass
                raise AppError(
                    code="GIT_OPERATION_FAILED",
                    message=f"Git 操作失败: {masked_stderr.strip() or '未知错误'}",
                    status_code=400,
                )
            return res
        except subprocess.TimeoutExpired:
            try:
                logger.error("Git 命令执行超时", args=args, timeout=timeout)
            except Exception:
                pass
            raise AppError(
                code="GIT_OPERATION_TIMEOUT",
                message="Git 操作超时，请检查网络或配置",
                status_code=408,
            )
        finally:
            # 物理擦除临时私钥文件
            if temp_ssh_path and os.path.exists(temp_ssh_path):
                try:
                    size = os.path.getsize(temp_ssh_path)
                    with open(temp_ssh_path, "wb") as f_erase:
                        f_erase.write(b"\x00" * size)
                    os.remove(temp_ssh_path)
                except Exception:
                    pass

    @classmethod
    def verify_connection(
        cls,
        remote_url: str,
        auth_type: str,
        credential_content: str | None = None,
        main_branch: str = "main",
    ) -> None:
        if not remote_url or not (
            remote_url.startswith("git@")
            or remote_url.startswith("http://")
            or remote_url.startswith("https://")
        ):
            raise AppError(
                code="INVALID_REPOSITORY_URL",
                message="Git 仓库地址格式非法，须为 git@ 或 http(s):// 开头",
                status_code=400,
            )

        target_url = remote_url
        if auth_type == "HTTP_TOKEN" and credential_content:
            parsed = urlparse(remote_url)
            if parsed.scheme in ("http", "https"):
                token = credential_content.strip()
                netloc_with_token = f"x-token-auth:{token}@{parsed.netloc}"
                target_url = parsed._replace(netloc=netloc_with_token).geturl()

        # ls-remote 仅查询指定主干是否存在，极大减小网络和命令时间
        args = ["git", "ls-remote", "-h", target_url, main_branch]
        cls.run_git_command(
            args, auth_type=auth_type, credential_content=credential_content
        )
