import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from testweave.core.errors import AppError
from testweave.infrastructure.git import GitClient

PUBLIC_ADDRESS_INFO = [
    (2, 1, 6, "", ("93.184.216.34", 443)),
]


def git_config_values(env: dict[str, str], key: str) -> list[str]:
    count = int(env["GIT_CONFIG_COUNT"])
    return [
        env[f"GIT_CONFIG_VALUE_{index}"]
        for index in range(count)
        if env[f"GIT_CONFIG_KEY_{index}"] == key
    ]


def test_git_client_mask_sensitive() -> None:
    # 验证 URL token 屏蔽
    url = "https://x-token-auth:my_secret_token_123@github.com/org/repo.git"
    masked = GitClient._mask_sensitive(url)
    assert "my_secret_token_123" not in masked
    assert "https://x-token-auth:***@github.com/org/repo.git" in masked

    # 验证私钥明文屏蔽
    private_key = (
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAz874...\n-----END RSA PRIVATE KEY-----"
    )
    masked_key = GitClient._mask_sensitive(private_key)
    assert "MIIEow" not in masked_key
    assert "[PRIVATE KEY MASKED]" in masked_key


@patch("subprocess.run")
def test_git_client_run_command_ssh_temp_file_clean(mock_run: MagicMock) -> None:
    # 模拟 subprocess 运行成功
    mock_run.return_value = subprocess.CompletedProcess(
        args=["git", "ls-remote"], returncode=0, stdout="success_output", stderr=""
    )

    private_key_content = "MOCK_PRIVATE_KEY_CONTENT"

    # 用 patch 追踪临时私钥生成，确保其执行后被物理擦除
    temp_path = None
    original_chmod = os.chmod

    def mock_chmod(path: str, mode: int) -> None:
        nonlocal temp_path
        temp_path = path
        original_chmod(path, mode)

    with patch("os.chmod", side_effect=mock_chmod):
        GitClient.run_git_command(
            args=["git", "ls-remote"],
            auth_type="SSH_KEY",
            credential_content=private_key_content,
        )

    # 1. 验证 subprocess 接收到了临时私钥的环境变量注入
    assert mock_run.call_count == 1
    call_kwargs = mock_run.call_args[1]
    assert "env" in call_kwargs
    git_ssh = call_kwargs["env"].get("GIT_SSH_COMMAND", "")
    assert "-i " in git_ssh
    assert temp_path in git_ssh
    assert "StrictHostKeyChecking=yes" in git_ssh
    assert "StrictHostKeyChecking=no" not in git_ssh
    assert "UserKnownHostsFile=/dev/null" not in git_ssh
    assert "IdentityFile=none" in git_ssh

    # 2. 验证临时私钥文件已被物理擦除并删除
    assert temp_path is not None
    assert not os.path.exists(temp_path)


@patch("subprocess.run")
def test_git_client_http_token_uses_temporary_askpass_and_redacts_failure(
    mock_run: MagicMock,
) -> None:
    token = "synthetic-http-token-REQ-10002"
    captured: dict[str, object] = {}

    def fail_with_secret(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        env = dict(kwargs["env"])  # type: ignore[arg-type]
        askpass_path = str(env["GIT_ASKPASS"])
        captured["args"] = list(args)
        captured["env"] = env
        captured["askpass_path"] = askpass_path
        captured["askpass_content"] = Path(askpass_path).read_text()
        return subprocess.CompletedProcess(
            args=args,
            returncode=128,
            stdout="",
            stderr=f"fatal: authentication failed for {token}",
        )

    mock_run.side_effect = fail_with_secret

    with (
        patch("testweave.infrastructure.git.logger.warning") as mock_warning,
        pytest.raises(AppError) as exc_info,
    ):
        GitClient.run_git_command(
            args=["git", "ls-remote", "https://example.com/org/repo.git"],
            auth_type="HTTP_TOKEN",
            credential_content=token,
        )

    assert token not in repr(captured["args"])
    assert captured["env"]["TESTWEAVE_GIT_PASSWORD"] == token  # type: ignore[index]
    assert captured["env"]["GIT_ALLOW_PROTOCOL"] == "https:ssh"  # type: ignore[index]
    assert captured["env"]["GIT_CONFIG_KEY_1"] == "http.followRedirects"  # type: ignore[index]
    assert captured["env"]["GIT_CONFIG_VALUE_1"] == "false"  # type: ignore[index]
    assert token not in str(captured["askpass_content"])
    assert not Path(str(captured["askpass_path"])).exists()
    assert token not in exc_info.value.message
    assert token not in repr(mock_warning.call_args)


@patch("subprocess.run")
def test_git_client_http_token_never_enters_verify_argv(mock_run: MagicMock) -> None:
    token = "synthetic-verify-token-REQ-10002"
    captured_args: list[str] = []
    captured_env: dict[str, str] = {}

    def capture(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured_args.extend(args)
        captured_env.update(kwargs["env"])  # type: ignore[arg-type]
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    mock_run.side_effect = capture

    with patch(
        "testweave.infrastructure.git.socket.getaddrinfo",
        return_value=PUBLIC_ADDRESS_INFO,
    ):
        GitClient.verify_connection(
            remote_url="https://example.com/org/repo.git",
            auth_type="HTTP_TOKEN",
            credential_content=token,
        )

    assert captured_args == [
        "git",
        "ls-remote",
        "--exit-code",
        "--heads",
        "https://example.com/org/repo.git",
        "refs/heads/main",
    ]
    assert token not in repr(captured_args)
    assert git_config_values(captured_env, "http.curloptResolve") == [
        "example.com:443:93.184.216.34"
    ]


@patch("subprocess.run")
def test_git_client_https_pin_ignores_proxy_environment(mock_run: MagicMock) -> None:
    captured_env: dict[str, str] = {}

    def capture(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured_env.update(kwargs["env"])  # type: ignore[arg-type]
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    mock_run.side_effect = capture
    with (
        patch.dict(
            os.environ,
            {
                "HTTPS_PROXY": "http://127.0.0.1:3128",
                "https_proxy": "http://127.0.0.1:3128",
                "ALL_PROXY": "socks5://127.0.0.1:1080",
            },
        ),
        patch(
            "testweave.infrastructure.git.socket.getaddrinfo",
            return_value=PUBLIC_ADDRESS_INFO,
        ),
    ):
        GitClient.verify_connection(
            remote_url="https://example.com/org/repo.git",
            auth_type="NONE",
        )

    assert "HTTPS_PROXY" not in captured_env
    assert "https_proxy" not in captured_env
    assert "ALL_PROXY" not in captured_env
    assert captured_env["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert captured_env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert git_config_values(captured_env, "http.proxy") == [""]
    assert git_config_values(captured_env, "remote.origin.proxy") == [""]


@patch("subprocess.run")
def test_git_client_https_pin_supports_ipv6(mock_run: MagicMock) -> None:
    captured_env: dict[str, str] = {}
    public_ipv6 = "2606:2800:220:1:248:1893:25c8:1946"

    def capture(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured_env.update(kwargs["env"])  # type: ignore[arg-type]
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    mock_run.side_effect = capture
    with patch(
        "testweave.infrastructure.git.socket.getaddrinfo",
        return_value=[(10, 1, 6, "", (public_ipv6, 443, 0, 0))],
    ):
        GitClient.verify_connection(
            remote_url="https://example.com/org/repo.git",
            auth_type="NONE",
        )

    assert git_config_values(captured_env, "http.curloptResolve") == [
        f"example.com:443:[{public_ipv6}]"
    ]


@patch("subprocess.run")
def test_git_client_pins_ssh_target_and_disables_default_identities(
    mock_run: MagicMock,
) -> None:
    captured_env: dict[str, str] = {}

    def capture(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured_env.update(kwargs["env"])  # type: ignore[arg-type]
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    mock_run.side_effect = capture
    with patch(
        "testweave.infrastructure.git.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("93.184.216.34", 22))],
    ):
        GitClient.verify_connection(
            remote_url="ssh://git@example.com/org/repo.git",
            auth_type="SSH_KEY",
            credential_content="SYNTHETIC_PRIVATE_KEY",
        )

    git_ssh_command = captured_env["GIT_SSH_COMMAND"]
    assert "HostName=93.184.216.34" in git_ssh_command
    assert "HostKeyAlias=example.com" in git_ssh_command
    assert "IdentityFile=none" in git_ssh_command
    assert "IdentityAgent=none" in git_ssh_command
    assert "ProxyCommand=none" in git_ssh_command
    assert "ProxyJump=none" in git_ssh_command


@patch("subprocess.run")
def test_git_client_missing_main_branch_fails_verification(mock_run: MagicMock) -> None:
    mock_run.return_value = subprocess.CompletedProcess(
        args=["git", "ls-remote"],
        returncode=2,
        stdout="",
        stderr="",
    )

    with (
        patch(
            "testweave.infrastructure.git.socket.getaddrinfo",
            return_value=PUBLIC_ADDRESS_INFO,
        ),
        pytest.raises(AppError) as exc_info,
    ):
        GitClient.verify_connection(
            remote_url="https://example.com/org/repo.git",
            auth_type="NONE",
            main_branch="missing",
        )

    assert exc_info.value.code == "GIT_OPERATION_FAILED"


@pytest.mark.parametrize(
    "remote_url",
    [
        "http://example.com/org/repo.git",
        "git://example.com/org/repo.git",
        "file:///tmp/repo.git",
        "https://user:secret@example.com/org/repo.git",
        "ftp://example.com/org/repo.git",
    ],
)
def test_git_client_rejects_unsafe_protocols_and_url_credentials(remote_url: str) -> None:
    with pytest.raises(AppError) as exc_info:
        GitClient.verify_connection(remote_url=remote_url, auth_type="NONE")

    assert exc_info.value.code == "INVALID_REPOSITORY_URL"


@pytest.mark.parametrize(
    ("remote_url", "resolved_ip"),
    [
        ("https://127.0.0.1/repo.git", "127.0.0.1"),
        ("https://private.example/repo.git", "10.0.0.8"),
        ("https://link-local.example/repo.git", "169.254.169.254"),
        ("ssh://git@multicast.example/repo.git", "224.0.0.1"),
        ("git@reserved.example:org/repo.git", "240.0.0.1"),
    ],
)
def test_git_client_rejects_non_public_repository_targets(
    remote_url: str,
    resolved_ip: str,
) -> None:
    address_info = [(2, 1, 6, "", (resolved_ip, 443))]

    with (
        patch("testweave.infrastructure.git.socket.getaddrinfo", return_value=address_info),
        patch("subprocess.run") as mock_run,
        pytest.raises(AppError) as exc_info,
    ):
        GitClient.verify_connection(remote_url=remote_url, auth_type="NONE")

    assert exc_info.value.code == "UNSAFE_REPOSITORY_TARGET"
    mock_run.assert_not_called()


@pytest.mark.parametrize(
    "remote_url",
    [
        "https://metadata.google.internal/computeMetadata/v1/",
        "ssh://git@metadata.azure.internal/org/repo.git",
    ],
)
def test_git_client_rejects_metadata_hostnames(remote_url: str) -> None:
    with (
        patch("testweave.infrastructure.git.socket.getaddrinfo") as mock_resolve,
        patch("subprocess.run") as mock_run,
        pytest.raises(AppError) as exc_info,
    ):
        GitClient.verify_connection(remote_url=remote_url, auth_type="NONE")

    assert exc_info.value.code == "UNSAFE_REPOSITORY_TARGET"
    mock_resolve.assert_not_called()
    mock_run.assert_not_called()


def test_git_client_rejects_hostname_with_mixed_public_and_private_answers() -> None:
    address_info = [
        (2, 1, 6, "", ("93.184.216.34", 443)),
        (2, 1, 6, "", ("192.168.1.10", 443)),
    ]

    with (
        patch("testweave.infrastructure.git.socket.getaddrinfo", return_value=address_info),
        patch("subprocess.run") as mock_run,
        pytest.raises(AppError) as exc_info,
    ):
        GitClient.verify_connection(
            remote_url="https://mixed.example/org/repo.git",
            auth_type="NONE",
        )

    assert exc_info.value.code == "UNSAFE_REPOSITORY_TARGET"
    mock_run.assert_not_called()


@patch("subprocess.run")
def test_git_client_ssh_uses_configured_known_hosts(mock_run: MagicMock, tmp_path: Path) -> None:
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("github.com ssh-ed25519 synthetic-key\n")
    captured_env: dict[str, str] = {}

    def capture(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured_env.update(kwargs["env"])  # type: ignore[arg-type]
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    mock_run.side_effect = capture

    with patch.dict(
        os.environ,
        {"TESTWEAVE_GIT_KNOWN_HOSTS_FILE": str(known_hosts)},
    ):
        GitClient.run_git_command(
            args=["git", "ls-remote", "git@github.com:org/repo.git"],
            auth_type="SSH_KEY",
            credential_content="SYNTHETIC_PRIVATE_KEY",
        )

    git_ssh_command = captured_env["GIT_SSH_COMMAND"]
    assert "StrictHostKeyChecking=yes" in git_ssh_command
    assert f"UserKnownHostsFile={known_hosts}" in git_ssh_command
    assert "UserKnownHostsFile=/dev/null" not in git_ssh_command


@patch("subprocess.run")
def test_git_client_ssh_uses_settings_known_hosts(mock_run: MagicMock, tmp_path: Path) -> None:
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("github.com ssh-ed25519 synthetic-key\n")
    mock_run.return_value = subprocess.CompletedProcess(
        args=["git", "ls-remote"],
        returncode=0,
        stdout="",
        stderr="",
    )

    with (
        patch.dict(os.environ, {"TESTWEAVE_GIT_KNOWN_HOSTS_FILE": ""}),
        patch(
            "testweave.infrastructure.git.get_settings",
            return_value=SimpleNamespace(git_known_hosts_file=str(known_hosts)),
        ),
    ):
        GitClient.run_git_command(
            args=["git", "ls-remote", "git@github.com:org/repo.git"],
            auth_type="SSH_KEY",
            credential_content="SYNTHETIC_PRIVATE_KEY",
        )

    git_ssh_command = mock_run.call_args.kwargs["env"]["GIT_SSH_COMMAND"]
    assert f"UserKnownHostsFile={known_hosts}" in git_ssh_command


@patch("subprocess.run")
def test_git_client_ssh_without_private_key_still_requires_known_host(
    mock_run: MagicMock,
) -> None:
    mock_run.return_value = subprocess.CompletedProcess(
        args=["git", "ls-remote"],
        returncode=0,
        stdout="",
        stderr="",
    )

    GitClient.run_git_command(
        args=["git", "ls-remote", "git@github.com:org/repo.git"],
        auth_type="NONE",
    )

    git_ssh_command = mock_run.call_args.kwargs["env"].get("GIT_SSH_COMMAND", "")
    assert "StrictHostKeyChecking=yes" in git_ssh_command
    assert "UserKnownHostsFile=/dev/null" not in git_ssh_command


@patch("subprocess.run")
def test_git_client_ssh_without_private_key_disables_ambient_credentials(
    mock_run: MagicMock,
) -> None:
    mock_run.return_value = subprocess.CompletedProcess(
        args=["git", "ls-remote"],
        returncode=0,
        stdout="",
        stderr="",
    )

    GitClient.run_git_command(
        args=["git", "ls-remote", "git@github.com:org/repo.git"],
        auth_type="NONE",
    )

    git_ssh_command = mock_run.call_args.kwargs["env"]["GIT_SSH_COMMAND"]
    assert "IdentitiesOnly=yes" in git_ssh_command
    assert "IdentityAgent=none" in git_ssh_command
    assert "IdentityFile=none" in git_ssh_command


@pytest.mark.parametrize(
    "main_branch",
    [
        "--output=/tmp/testweave-branch-injection",
        "../main",
        "feature//unsafe",
        "feature/@{unsafe",
        "feature/unsafe.lock",
        "feature/unsafe.",
    ],
)
def test_git_client_rejects_unsafe_main_branch(main_branch: str) -> None:
    with (
        patch(
            "testweave.infrastructure.git.socket.getaddrinfo",
            return_value=PUBLIC_ADDRESS_INFO,
        ),
        patch("subprocess.run") as mock_run,
        pytest.raises(AppError) as exc_info,
    ):
        GitClient.verify_connection(
            remote_url="https://example.com/org/repo.git",
            auth_type="NONE",
            main_branch=main_branch,
        )

    assert exc_info.value.code == "INVALID_MAIN_BRANCH"
    mock_run.assert_not_called()


@patch("subprocess.run")
def test_git_client_run_command_timeout(mock_run: MagicMock) -> None:
    # 模拟超时异常
    mock_run.side_effect = subprocess.TimeoutExpired(cmd=["git"], timeout=30)

    with pytest.raises(AppError) as exc_info:
        GitClient.run_git_command(args=["git", "status"])
    assert exc_info.value.code == "GIT_OPERATION_TIMEOUT"
