import ipaddress
import os
import re
import shlex
import socket
import subprocess
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from urllib.parse import urlsplit

import structlog

from testweave.core.config import get_settings
from testweave.core.errors import AppError

logger = structlog.get_logger()


@dataclass(frozen=True)
class GitRemoteTarget:
    remote_url: str
    hostname: str
    port: int
    address: str
    is_ssh: bool


class GitClient:
    _HTTP_AUTH_TYPES = frozenset({"HTTP_TOKEN", "HTTPS_TOKEN"})
    _AUTH_TYPES = frozenset({"NONE", "HTTP_TOKEN", "HTTPS_TOKEN", "SSH_KEY"})
    _INVALID_BRANCH_CHARACTER_PATTERN = re.compile(r"[\x00-\x20\x7f~^:?*\[\\]")
    _SCP_REMOTE_PATTERN = re.compile(
        r"^(?P<user>[A-Za-z0-9._-]+)@"
        r"(?P<host>\[[0-9A-Fa-f:.%]+\]|[A-Za-z0-9.-]+):"
        r"(?P<path>[^\s]+)$"
    )
    _METADATA_HOSTNAMES = frozenset(
        {
            "instance-data.ec2.internal",
            "metadata",
            "metadata.azure.internal",
            "metadata.google.internal",
            "metadata.google",
            "metadata.oraclecloud.com",
        }
    )
    _ASKPASS_SCRIPT = """#!/bin/sh
case "$1" in
  *sername*) printf '%s\\n' "$TESTWEAVE_GIT_USERNAME" ;;
  *assword*) printf '%s\\n' "$TESTWEAVE_GIT_PASSWORD" ;;
  *) exit 1 ;;
esac
"""

    @staticmethod
    def _mask_sensitive(text: str, *secrets: str | None) -> str:
        if not text:
            return ""

        masked = text
        for secret in secrets:
            if secret:
                masked = masked.replace(secret, "***")
                stripped_secret = secret.strip()
                if stripped_secret:
                    masked = masked.replace(stripped_secret, "***")

        masked = re.sub(
            r"-----BEGIN [A-Z ]+ PRIVATE KEY-----[\s\S]+?"
            r"-----END [A-Z ]+ PRIVATE KEY-----",
            "[PRIVATE KEY MASKED]",
            masked,
        )
        masked = re.sub(
            r"(?i)(https?://)([^:/@\s]+):([^@\s]+)(@)",
            r"\1\2:***\4",
            masked,
        )
        masked = re.sub(
            r"(?i)(https?://)([^:/@\s]+)(@)",
            r"\1***\3",
            masked,
        )
        masked = re.sub(
            r"(?i)(authorization\s*:\s*(?:basic|bearer)\s+)[^\s,;]+",
            r"\1***",
            masked,
        )
        return re.sub(
            r"(?i)([?&](?:access_token|auth_token|password|token)=)[^&#\s]+",
            r"\1***",
            masked,
        )

    @classmethod
    def _masked_args(
        cls,
        args: list[str],
        credential_content: str | None,
    ) -> list[str]:
        return [cls._mask_sensitive(arg, credential_content) for arg in args]

    @staticmethod
    def _secure_remove(path: str | None) -> None:
        if not path or not os.path.exists(path):
            return
        try:
            size = os.path.getsize(path)
            with open(path, "r+b") as temporary_file:
                temporary_file.write(b"\x00" * size)
                temporary_file.flush()
            os.remove(path)
        except OSError:
            with suppress(OSError):
                os.remove(path)

    @classmethod
    def _write_temporary_file(cls, content: str, *, suffix: str, mode: int) -> str:
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                delete=False,
                suffix=suffix,
                encoding="utf-8",
                newline="\n",
            ) as temporary_file:
                temporary_path = temporary_file.name
                temporary_file.write(content)
            os.chmod(temporary_path, mode)
            return temporary_path
        except Exception:
            cls._secure_remove(temporary_path)
            raise

    @staticmethod
    def _append_git_config(env: dict[str, str], key: str, value: str) -> None:
        count = int(env.get("GIT_CONFIG_COUNT", "0"))
        env[f"GIT_CONFIG_KEY_{count}"] = key
        env[f"GIT_CONFIG_VALUE_{count}"] = value
        env["GIT_CONFIG_COUNT"] = str(count + 1)

    @staticmethod
    def _configure_safe_git_environment(env: dict[str, str]) -> None:
        for key in tuple(env):
            if key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
                env.pop(key, None)
        for key in (
            "GIT_ASKPASS",
            "GIT_CONFIG_COUNT",
            "GIT_CONFIG_GLOBAL",
            "GIT_CONFIG_NOSYSTEM",
            "GIT_CONFIG_PARAMETERS",
            "GIT_CONFIG_SYSTEM",
            "GIT_DIR",
            "GIT_PROXY_COMMAND",
            "GIT_SSH",
            "GIT_SSH_COMMAND",
            "GIT_SSH_VARIANT",
            "GIT_WORK_TREE",
            "SSH_ASKPASS",
        ):
            env.pop(key, None)

        for key in (
            "ALL_PROXY",
            "HTTPS_PROXY",
            "HTTP_PROXY",
            "NO_PROXY",
            "all_proxy",
            "https_proxy",
            "http_proxy",
            "no_proxy",
        ):
            env.pop(key, None)

        env.update(
            {
                "GIT_ALLOW_PROTOCOL": "https:ssh",
                "GIT_CONFIG_COUNT": "0",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
            }
        )
        GitClient._append_git_config(env, "credential.helper", "")
        GitClient._append_git_config(env, "http.followRedirects", "false")
        GitClient._append_git_config(env, "http.proxy", "")
        GitClient._append_git_config(env, "remote.origin.proxy", "")

    @classmethod
    def _configure_http_token(
        cls,
        env: dict[str, str],
        credential_content: str,
    ) -> str:
        askpass_path = cls._write_temporary_file(
            cls._ASKPASS_SCRIPT,
            suffix="_git_askpass",
            mode=0o700,
        )
        env.update(
            {
                "GIT_ASKPASS": askpass_path,
                "TESTWEAVE_GIT_PASSWORD": credential_content.strip(),
                "TESTWEAVE_GIT_USERNAME": "x-token-auth",
            }
        )
        return askpass_path

    @classmethod
    def _configure_ssh_key(
        cls,
        env: dict[str, str],
        credential_content: str,
        remote_target: GitRemoteTarget | None = None,
    ) -> str:
        private_key_path = cls._write_temporary_file(
            credential_content.strip() + "\n",
            suffix="_git_ssh_key",
            mode=0o600,
        )
        cls._configure_strict_ssh(
            env,
            private_key_path=private_key_path,
            remote_target=remote_target,
        )
        return private_key_path

    @staticmethod
    def _configure_strict_ssh(
        env: dict[str, str],
        *,
        private_key_path: str | None = None,
        remote_target: GitRemoteTarget | None = None,
    ) -> None:
        ssh_options = [
            "ssh",
            "-F",
            "/dev/null",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "IdentityAgent=none",
            "-o",
            "IdentityFile=none",
            "-o",
            "ProxyCommand=none",
            "-o",
            "ProxyJump=none",
            "-o",
            "ClearAllForwardings=yes",
        ]
        if private_key_path:
            ssh_options.extend(["-i", private_key_path])
        if remote_target and remote_target.is_ssh:
            ssh_options.extend(
                [
                    "-o",
                    f"HostName={remote_target.address}",
                    "-o",
                    f"HostKeyAlias={remote_target.hostname}",
                ]
            )
        known_hosts_path = env.get("TESTWEAVE_GIT_KNOWN_HOSTS_FILE")
        if not known_hosts_path:
            known_hosts_path = get_settings().git_known_hosts_file
        if known_hosts_path:
            known_hosts_path = os.path.abspath(os.path.expanduser(known_hosts_path))
            ssh_options.extend(["-o", f"UserKnownHostsFile={known_hosts_path}"])
        env["GIT_SSH_COMMAND"] = " ".join(shlex.quote(option) for option in ssh_options)
        env["GIT_SSH_VARIANT"] = "ssh"

    @classmethod
    def run_git_command(
        cls,
        args: list[str],
        auth_type: str = "NONE",
        credential_content: str | None = None,
        timeout: int = 30,
        remote_target: GitRemoteTarget | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        askpass_path: str | None = None
        private_key_path: str | None = None
        cls._configure_safe_git_environment(env)
        cls._configure_strict_ssh(env, remote_target=remote_target)
        if remote_target and not remote_target.is_ssh:
            pinned_address = (
                f"[{remote_target.address}]"
                if ":" in remote_target.address
                else remote_target.address
            )
            cls._append_git_config(
                env,
                "http.curloptResolve",
                f"{remote_target.hostname}:{remote_target.port}:{pinned_address}",
            )

        try:
            if auth_type in cls._HTTP_AUTH_TYPES and credential_content:
                askpass_path = cls._configure_http_token(env, credential_content)
            elif auth_type == "SSH_KEY" and credential_content:
                private_key_path = cls._configure_ssh_key(
                    env,
                    credential_content,
                    remote_target=remote_target,
                )

            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                env=env,
                timeout=timeout,
            )
            masked_stderr = cls._mask_sensitive(result.stderr, credential_content)

            if result.returncode != 0:
                with suppress(Exception):
                    logger.warning(
                        "Git 命令执行失败",
                        args=cls._masked_args(args, credential_content),
                        returncode=result.returncode,
                        stderr=masked_stderr,
                    )
                raise AppError(
                    code="GIT_OPERATION_FAILED",
                    message=f"Git 操作失败: {masked_stderr.strip() or '未知错误'}",
                    status_code=400,
                )
            return subprocess.CompletedProcess(
                args=cls._masked_args(args, credential_content),
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=masked_stderr,
            )
        except subprocess.TimeoutExpired:
            with suppress(Exception):
                logger.error(
                    "Git 命令执行超时",
                    args=cls._masked_args(args, credential_content),
                    timeout=timeout,
                )
            raise AppError(
                code="GIT_OPERATION_TIMEOUT",
                message="Git 操作超时，请检查网络或配置",
                status_code=408,
            ) from None
        except AppError:
            raise
        except Exception as error:
            safe_error = cls._mask_sensitive(str(error), credential_content)
            with suppress(Exception):
                logger.error(
                    "Git 命令无法执行",
                    args=cls._masked_args(args, credential_content),
                    error_type=type(error).__name__,
                    error=safe_error,
                )
            raise AppError(
                code="GIT_OPERATION_FAILED",
                message=f"Git 操作失败: {safe_error.strip() or '未知错误'}",
                status_code=400,
            ) from None
        finally:
            env.pop("TESTWEAVE_GIT_PASSWORD", None)
            env.pop("TESTWEAVE_GIT_USERNAME", None)
            cls._secure_remove(askpass_path)
            cls._secure_remove(private_key_path)

    @classmethod
    def _validate_target_host(cls, hostname: str, port: int) -> str:
        normalized_host = hostname.rstrip(".").lower()
        if (
            normalized_host in cls._METADATA_HOSTNAMES
            or normalized_host == "localhost"
            or normalized_host.endswith(".localhost")
        ):
            raise AppError(
                code="UNSAFE_REPOSITORY_TARGET",
                message="Git 仓库地址指向不允许访问的网络目标",
                status_code=400,
            )

        try:
            ascii_host = normalized_host.encode("idna").decode("ascii")
            address_info = socket.getaddrinfo(
                ascii_host,
                port,
                type=socket.SOCK_STREAM,
            )
        except (OSError, UnicodeError):
            raise AppError(
                code="INVALID_REPOSITORY_URL",
                message="Git 仓库主机无法安全解析",
                status_code=400,
            ) from None

        addresses = {str(item[4][0]).split("%", maxsplit=1)[0] for item in address_info}
        if not addresses:
            raise AppError(
                code="INVALID_REPOSITORY_URL",
                message="Git 仓库主机无法安全解析",
                status_code=400,
            )

        try:
            parsed_addresses = [ipaddress.ip_address(address) for address in addresses]
        except ValueError:
            raise AppError(
                code="INVALID_REPOSITORY_URL",
                message="Git 仓库主机解析结果非法",
                status_code=400,
            ) from None

        if any(
            not address.is_global
            or address.is_link_local
            or address.is_loopback
            or address.is_multicast
            or address.is_private
            or address.is_reserved
            or address.is_unspecified
            for address in parsed_addresses
        ):
            raise AppError(
                code="UNSAFE_REPOSITORY_TARGET",
                message="Git 仓库地址指向不允许访问的网络目标",
                status_code=400,
            )
        selected_address = min(
            parsed_addresses,
            key=lambda address: (address.version, int(address)),
        )
        return str(selected_address)

    @classmethod
    def _parse_remote_url(cls, remote_url: str) -> tuple[str, str, int, bool]:
        normalized_url = remote_url.strip()
        if (
            not normalized_url
            or "\\" in normalized_url
            or any(character.isspace() for character in normalized_url)
            or any(ord(character) < 32 or ord(character) == 127 for character in normalized_url)
        ):
            raise AppError(
                code="INVALID_REPOSITORY_URL",
                message="Git 仓库地址格式非法，仅支持 HTTPS 或 SSH 地址",
                status_code=400,
            )

        scp_match = cls._SCP_REMOTE_PATTERN.fullmatch(normalized_url)
        if scp_match:
            hostname = scp_match.group("host").removeprefix("[").removesuffix("]")
            return normalized_url, hostname, 22, True

        try:
            parsed = urlsplit(normalized_url)
            port = parsed.port
        except ValueError:
            parsed = None
            port = None

        if parsed is None or parsed.scheme.lower() not in {"https", "ssh"}:
            raise AppError(
                code="INVALID_REPOSITORY_URL",
                message="Git 仓库地址格式非法，仅支持 HTTPS 或 SSH 地址",
                status_code=400,
            )
        if (
            not parsed.hostname
            or parsed.query
            or parsed.fragment
            or parsed.password is not None
            or (parsed.scheme.lower() == "https" and parsed.username is not None)
        ):
            raise AppError(
                code="INVALID_REPOSITORY_URL",
                message="Git 仓库地址不得包含凭证、查询参数或片段",
                status_code=400,
            )

        default_port = 443 if parsed.scheme.lower() == "https" else 22
        return normalized_url, parsed.hostname, port or default_port, parsed.scheme.lower() == "ssh"

    @classmethod
    def validate_remote_url_syntax(cls, remote_url: str) -> str:
        normalized_url, hostname, _, _ = cls._parse_remote_url(remote_url)
        normalized_hostname = hostname.rstrip(".").lower()
        if (
            normalized_hostname in cls._METADATA_HOSTNAMES
            or normalized_hostname == "localhost"
            or normalized_hostname.endswith(".localhost")
        ):
            raise AppError(
                code="UNSAFE_REPOSITORY_TARGET",
                message="Git 仓库地址指向不允许访问的网络目标",
                status_code=400,
            )
        return normalized_url

    @classmethod
    def resolve_remote_target(cls, remote_url: str) -> GitRemoteTarget:
        normalized_url, hostname, port, is_ssh = cls._parse_remote_url(remote_url)
        address = cls._validate_target_host(hostname, port)
        ascii_hostname = hostname.rstrip(".").encode("idna").decode("ascii")
        return GitRemoteTarget(
            remote_url=normalized_url,
            hostname=ascii_hostname.lower(),
            port=port,
            address=address,
            is_ssh=is_ssh,
        )

    @classmethod
    def validate_remote_url(cls, remote_url: str) -> str:
        return cls.resolve_remote_target(remote_url).remote_url

    @classmethod
    def validate_main_branch(cls, main_branch: str) -> str:
        normalized_branch = main_branch.strip()
        components = normalized_branch.split("/")
        if (
            not normalized_branch
            or len(normalized_branch) > 255
            or normalized_branch.startswith("-")
            or normalized_branch == "@"
            or normalized_branch.endswith(("/", "."))
            or ".." in normalized_branch
            or "@{" in normalized_branch
            or cls._INVALID_BRANCH_CHARACTER_PATTERN.search(normalized_branch)
            or any(
                not component or component.startswith(".") or component.endswith((".lock", "."))
                for component in components
            )
        ):
            raise AppError(
                code="INVALID_MAIN_BRANCH",
                message="Git 主干分支名格式非法",
                status_code=400,
            )
        return normalized_branch

    @classmethod
    def validate_auth_type(cls, auth_type: str) -> str:
        normalized_auth_type = auth_type.strip().upper()
        if normalized_auth_type not in cls._AUTH_TYPES:
            raise AppError(
                code="INVALID_REPOSITORY_AUTH",
                message="Git 仓库认证方式非法",
                status_code=400,
            )
        return normalized_auth_type

    @classmethod
    def validate_auth_configuration(
        cls,
        remote_url: str,
        auth_type: str,
        credential_content: str | None,
    ) -> str:
        normalized_auth_type = cls.validate_auth_type(auth_type)
        is_ssh_remote = (
            bool(cls._SCP_REMOTE_PATTERN.fullmatch(remote_url))
            or urlsplit(remote_url).scheme.lower() == "ssh"
        )
        allowed_auth_types = (
            {"NONE", "SSH_KEY"}
            if is_ssh_remote
            else {
                "NONE",
                *cls._HTTP_AUTH_TYPES,
            }
        )
        if normalized_auth_type not in allowed_auth_types:
            raise AppError(
                code="INVALID_REPOSITORY_AUTH",
                message="Git 仓库地址与认证方式不匹配",
                status_code=400,
            )
        if normalized_auth_type != "NONE" and not (
            credential_content and credential_content.strip()
        ):
            raise AppError(
                code="REPOSITORY_CREDENTIAL_REQUIRED",
                message="当前认证方式必须提供新的仓库凭证",
                status_code=400,
            )
        return normalized_auth_type

    @classmethod
    def verify_connection(
        cls,
        remote_url: str,
        auth_type: str,
        credential_content: str | None = None,
        main_branch: str = "main",
    ) -> None:
        remote_target = cls.resolve_remote_target(remote_url)
        safe_remote_url = remote_target.remote_url
        safe_main_branch = cls.validate_main_branch(main_branch)
        safe_auth_type = cls.validate_auth_configuration(
            safe_remote_url,
            auth_type,
            credential_content,
        )
        args = [
            "git",
            "ls-remote",
            "--exit-code",
            "--heads",
            safe_remote_url,
            f"refs/heads/{safe_main_branch}",
        ]
        cls.run_git_command(
            args,
            auth_type=safe_auth_type,
            credential_content=credential_content,
            remote_target=remote_target,
        )
