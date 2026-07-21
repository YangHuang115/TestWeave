import os
import subprocess
import pytest
from unittest.mock import patch, MagicMock

from testweave.core.errors import AppError
from testweave.infrastructure.git import GitClient


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

    # 2. 验证临时私钥文件已被物理擦除并删除
    assert temp_path is not None
    assert not os.path.exists(temp_path)


@patch("subprocess.run")
def test_git_client_run_command_timeout(mock_run: MagicMock) -> None:
    # 模拟超时异常
    mock_run.side_effect = subprocess.TimeoutExpired(cmd=["git"], timeout=30)

    with pytest.raises(AppError) as exc_info:
        GitClient.run_git_command(args=["git", "status"])
    assert exc_info.value.code == "GIT_OPERATION_TIMEOUT"
