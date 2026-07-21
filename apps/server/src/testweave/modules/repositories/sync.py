import gzip
import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import TypedDict

import structlog
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import CodeRepository, GitCommit, GitCommitFile, RepositorySyncJob
from testweave.infrastructure.git import GitClient
from testweave.shared.crypto import CryptoService

logger = structlog.get_logger()


class GitLogEntry(TypedDict):
    sha: str
    author_name: str
    author_email: str
    committer_name: str
    committer_email: str
    authored_at: int
    committed_at: int
    parent_shas: list[str]
    message: str


class GitFileStats(TypedDict, total=False):
    change_type: str
    old_path: str | None
    is_binary: bool
    additions: int
    deletions: int


class RepositorySyncManager:
    @staticmethod
    def create_sync_job(
        db: Session,
        project_id: str,
        repository_id: str,
        actor_id: str | None = None,
    ) -> RepositorySyncJob:
        # 检查是否已有活跃的同步任务在运行以防止重入
        active_stmt = select(RepositorySyncJob).where(
            RepositorySyncJob.repository_id == uuid.UUID(str(repository_id)),
            RepositorySyncJob.status.in_(["PENDING", "RUNNING"]),
        )
        active_job = db.scalar(active_stmt)
        if active_job:
            return active_job

        job = RepositorySyncJob(
            project_id=uuid.UUID(str(project_id)),
            repository_id=uuid.UUID(str(repository_id)),
            job_type="FULL_SYNC",
            status="PENDING",
            requested_by=uuid.UUID(str(actor_id)) if actor_id else None,
            attempt=0,
            available_at=datetime.now(UTC),
        )
        db.add(job)
        db.flush()
        return job

    @staticmethod
    def get_sync_job(db: Session, job_id: str) -> RepositorySyncJob | None:
        return db.get(RepositorySyncJob, uuid.UUID(str(job_id)))

    @classmethod
    def poll_and_execute_jobs(cls, db: Session, worker_id: str = "worker-default") -> int:
        """扫描并领取一个就绪的任务进行同步"""
        now = datetime.now(UTC)
        # 乐观抢占锁租约：找出 available_at <= now, 状态为 PENDING/FAILED 且 attempt < 5 的任务
        stmt = (
            select(RepositorySyncJob)
            .where(
                RepositorySyncJob.status.in_(["PENDING", "FAILED"]),
                RepositorySyncJob.attempt < 5,
                RepositorySyncJob.available_at <= now,
            )
            .limit(1)
        )

        job = db.scalar(stmt)
        if not job:
            return 0

        lease_until = datetime.now(UTC) + timedelta(minutes=10)

        job.status = "RUNNING"
        job.lease_owner = worker_id
        job.lease_until = lease_until
        job.started_at = datetime.now(UTC)
        job.attempt += 1
        db.flush()
        db.commit()

        # 执行抓取同步
        try:
            cls.sync_repository(db, str(job.repository_id), str(job.id))
            job.status = "COMPLETED"
            job.completed_at = datetime.now(UTC)
            job.error_code = None
            job.error_message = None
        except Exception as error:
            raw_error = getattr(error, "message", str(error))
            safe_error = GitClient._mask_sensitive(raw_error)
            logger.error(
                "仓库同步失败",
                job_id=job.id,
                repository_id=job.repository_id,
                error_type=type(error).__name__,
                error=safe_error,
            )
            db.rollback()
            # 标记失败
            job = db.get(RepositorySyncJob, job.id)
            if job:
                job.status = "FAILED"
                job.completed_at = datetime.now(UTC)
                job.error_code = getattr(error, "code", "SYNC_ERROR")
                job.error_message = safe_error
                # 退避 30s 重新可用
                job.available_at = datetime.now(UTC) + timedelta(seconds=30)

        db.flush()
        db.commit()
        return 1

    @classmethod
    def sync_repository(cls, db: Session, repository_id: str, job_id: str) -> None:
        repo = db.get(CodeRepository, uuid.UUID(str(repository_id)))
        if not repo or not repo.enabled:
            raise AppError(
                code="REPOSITORY_DISABLED",
                message="代码仓库已被禁用或不存在",
                status_code=400,
            )

        remote_target = GitClient.resolve_remote_target(repo.remote_url)
        safe_remote_url = remote_target.remote_url
        safe_main_branch = GitClient.validate_main_branch(repo.main_branch)

        # 解密凭证
        cred = CryptoService.decrypt(repo.credential_ref) if repo.credential_ref else None
        safe_auth_type = GitClient.validate_auth_configuration(
            safe_remote_url,
            repo.auth_type,
            cred,
        )

        # 本文件在 testweave/modules/repositories/sync.py，向上推五级定位 data。
        base_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..")
        )
        data_dir = os.path.join(base_dir, "data")
        if not os.path.exists(data_dir):
            data_dir = os.path.join(os.getcwd(), "data")

        # 确定克隆目录：/data/git_clones/{repo.id}.git
        clone_base = os.path.join(data_dir, "git_clones")
        os.makedirs(clone_base, exist_ok=True)
        local_dir = os.path.join(clone_base, f"{repo.id}.git")

        # 判断是否首次克隆
        if not os.path.exists(local_dir):
            # 首次 Mirror 克隆
            args = ["git", "clone", "--mirror", safe_remote_url, local_dir]
            GitClient.run_git_command(
                args,
                auth_type=safe_auth_type,
                credential_content=cred,
                remote_target=remote_target,
            )
        else:
            # 先将历史版本可能持久化的凭证 URL 替换为已校验的无凭证地址。
            set_remote_args = [
                "git",
                "--git-dir=" + local_dir,
                "remote",
                "set-url",
                "origin",
                safe_remote_url,
            ]
            GitClient.run_git_command(set_remote_args)
            # 只抓取已校验的 origin，避免本地配置中的额外 remote 触发外连。
            args = ["git", "--git-dir=" + local_dir, "fetch", "origin", "--prune"]
            GitClient.run_git_command(
                args,
                auth_type=safe_auth_type,
                credential_content=cred,
                remote_target=remote_target,
            )

        # 1. 抓取提交日志。如果是增量且 last_synced_head_sha 存在，尝试增量获取
        commits_data: list[GitLogEntry] = []
        is_force_push = False
        log_format = "%H|%an|%ae|%cn|%ce|%at|%ct|%P|%s"

        if repo.last_synced_head_sha:
            try:
                # 检查该 commit 在本地库中是否存在，若不存在直接触发 force-push 全量逻辑
                check_args = [
                    "git",
                    "--git-dir=" + local_dir,
                    "cat-file",
                    "-e",
                    repo.last_synced_head_sha,
                ]
                GitClient.run_git_command(check_args)

                args_log = [
                    "git",
                    "--git-dir=" + local_dir,
                    "log",
                    f"{repo.last_synced_head_sha}..{safe_main_branch}",
                    f"--pretty=format:{log_format}",
                ]
                res = GitClient.run_git_command(args_log)
                commits_data = cls._parse_git_log_output(res.stdout)
            except Exception:
                # 触发 unknown revision 错误，表明发生了 Force Push，需全量扫描重建
                is_force_push = True

        if not repo.last_synced_head_sha or is_force_push:
            args_log = [
                "git",
                "--git-dir=" + local_dir,
                "log",
                safe_main_branch,
                f"--pretty=format:{log_format}",
            ]
            res = GitClient.run_git_command(args_log)
            commits_data = cls._parse_git_log_output(res.stdout)

        # 2. 写入/更新 Commit 与 CommitFiles
        patch_base = os.path.join(data_dir, "patches", str(repo.id))

        # 为了高效处理，分批次处理
        new_head_sha = None
        if commits_data:
            new_head_sha = commits_data[0]["sha"]  # git log 默认最前为最新提交

        for c in reversed(commits_data):  # 从最老提交向最新提交写入，保证拓扑或时间自增
            sha = c["sha"]
            # 检查数据库是否已存在该 sha（全量扫描时防冲突）
            exist_stmt = select(GitCommit).where(
                GitCommit.repository_id == repo.id, GitCommit.sha == sha
            )
            db_commit = db.scalar(exist_stmt)

            if not db_commit:
                # 插入新的 commit 记录
                db_commit = GitCommit(
                    repository_id=repo.id,
                    sha=sha,
                    author_name=c["author_name"],
                    author_email=c["author_email"],
                    committer_name=c["committer_name"],
                    committer_email=c["committer_email"],
                    authored_at=datetime.fromtimestamp(c["authored_at"], UTC),
                    committed_at=datetime.fromtimestamp(c["committed_at"], UTC),
                    message=c["message"],
                    parent_shas_json=c["parent_shas"],
                    is_merge=len(c["parent_shas"]) > 1,
                    is_reachable_from_main=True,
                )
                db.add(db_commit)
                db.flush()

                # 获取该 commit 变动的文件及 diff patches
                # 1) 用 numstat 获取增加/删除行数
                cls._process_commit_files(db, local_dir, db_commit.id, sha, repo.id, patch_base)

        # 3. 校验并重建主干可达性
        # force_push 或增量扫描时，遍历该 repo 所有主干可达提交，
        # 并运行 git merge-base --is-ancestor 重新校准
        reach_stmt = select(GitCommit).where(
            GitCommit.repository_id == repo.id,
            GitCommit.is_reachable_from_main.is_(True),
        )
        active_commits = db.scalars(reach_stmt).all()
        for ac in active_commits:
            # 运行 ancestor 校验
            chk_args = [
                "git",
                "--git-dir=" + local_dir,
                "merge-base",
                "--is-ancestor",
                ac.sha,
                safe_main_branch,
            ]
            try:
                GitClient.run_git_command(chk_args)
            except Exception:
                # 退出码不为 0 代表已不可达
                ac.is_reachable_from_main = False

        # 4. 更新仓库最新 Head 与同步时间
        if new_head_sha:
            repo.last_synced_head_sha = new_head_sha
        repo.sync_status = "SYNCED"
        repo.last_success_at = datetime.now(UTC)
        repo.last_attempt_at = datetime.now(UTC)
        repo.last_error_code = None
        repo.last_error_message = None

        db.flush()

        # 5. 触发阶段 7 的“需求单号关联绑定匹配”
        from testweave.modules.repositories.matcher import MatcherService

        # 传入刚刚抓取出来的 commits shas 进行增量匹配
        newly_synced_shas = [c["sha"] for c in commits_data]
        if newly_synced_shas:
            MatcherService.match_commits_to_requirements(
                db,
                str(repo.project_id),
                str(repo.id),
                newly_synced_shas,
            )

    @classmethod
    def _parse_git_log_output(cls, output: str) -> list[GitLogEntry]:
        results: list[GitLogEntry] = []
        if not output.strip():
            return results
        for line in output.strip().split("\n"):
            parts = line.split("|", 8)
            if len(parts) < 9:
                continue
            sha = parts[0]
            aname = parts[1]
            aemail = parts[2]
            cname = parts[3]
            cemail = parts[4]
            try:
                atime = int(parts[5])
                ctime = int(parts[6])
            except ValueError:
                continue
            parents = parts[7].split() if parts[7] else []
            msg = parts[8]
            results.append(
                {
                    "sha": sha,
                    "author_name": aname,
                    "author_email": aemail,
                    "committer_name": cname,
                    "committer_email": cemail,
                    "authored_at": atime,
                    "committed_at": ctime,
                    "parent_shas": parents,
                    "message": msg,
                }
            )
        return results

    @classmethod
    def _process_commit_files(
        cls,
        db: Session,
        local_dir: str,
        commit_id: uuid.UUID,
        sha: str,
        repo_id: uuid.UUID,
        patch_base: str,
    ) -> None:
        # 使用 diff-tree 来精确分析该 commit 引起的文件改动，包括 old/new 路径、change_type 等
        # -r 递归，-m 包括 merge 修改，-c/--cc 联合格式
        args_files = [
            "git",
            "--git-dir=" + local_dir,
            "diff-tree",
            "--no-commit-id",
            "--name-status",
            "-r",
            "-m",
            sha,
        ]
        try:
            res = GitClient.run_git_command(args_files)
        except Exception:
            return

        file_lines = res.stdout.strip().split("\n") if res.stdout.strip() else []

        # 解析 name-status
        files_map: dict[str, GitFileStats] = {}
        for line in file_lines:
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            status = parts[0]
            new_path = parts[1]
            old_path = parts[2] if len(parts) > 2 else None

            # 单字母表示改动类型，若为 R (Rename) 或 C (Copy) 则可能带有 old_path
            change_type = "MODIFY"
            if status.startswith("A"):
                change_type = "ADD"
            elif status.startswith("D"):
                change_type = "DELETE"
            elif status.startswith("R"):
                change_type = "RENAME"

            files_map[new_path] = {
                "change_type": change_type,
                "old_path": old_path,
            }

        # 用 numstat 补充 additions/deletions 行数
        args_num = ["git", "--git-dir=" + local_dir, "show", "--format=", "--numstat", sha]
        try:
            res_num = GitClient.run_git_command(args_num)
            num_lines = res_num.stdout.strip().split("\n") if res_num.stdout.strip() else []
            for nline in num_lines:
                if not nline.strip():
                    continue
                parts = nline.split("\t")
                if len(parts) < 3:
                    continue
                add_str, del_str, filepath = parts[0], parts[1], parts[2]
                if filepath in files_map:
                    # 如果包含 "-" 说明是二进制文件
                    if add_str == "-" or del_str == "-":
                        files_map[filepath]["is_binary"] = True
                        files_map[filepath]["additions"] = 0
                        files_map[filepath]["deletions"] = 0
                    else:
                        files_map[filepath]["is_binary"] = False
                        files_map[filepath]["additions"] = int(add_str)
                        files_map[filepath]["deletions"] = int(del_str)
        except Exception:
            pass

        # 写入数据库并拉取具体 Patch 内容
        additions_total = 0
        deletions_total = 0
        files_count = 0

        for path, info in files_map.items():
            change_type = info["change_type"]
            old_path = info.get("old_path")
            is_binary = info.get("is_binary", False)
            add = info.get("additions", 0)
            del_val = info.get("deletions", 0)

            additions_total += add
            deletions_total += del_val
            files_count += 1

            # 抓取 patch 内容
            patch_content = ""
            patch_truncated = False
            patch_size = 0

            if not is_binary and change_type != "DELETE":
                # git show sha -- path
                args_patch = ["git", "--git-dir=" + local_dir, "show", "--format=", sha, "--", path]
                try:
                    res_p = GitClient.run_git_command(args_patch)
                    patch_content = res_p.stdout
                    patch_size = len(patch_content.encode("utf-8"))
                    # 限制最大 256KB 大小
                    if patch_size > 256 * 1024:
                        patch_content = patch_content[: 256 * 1024]
                        patch_truncated = True
                        patch_size = len(patch_content.encode("utf-8"))
                except Exception:
                    pass

            patch_key: str | None = None
            if patch_content:
                # 压缩 patch 存入 data/patches/{repo_id}/{sha}/{filename}.patch.gz
                sha_dir = os.path.join(patch_base, sha)
                os.makedirs(sha_dir, exist_ok=True)
                # 处理文件名防路径穿越
                safe_filename = re.sub(r"[^\w\-.]", "_", os.path.basename(path)) + ".patch.gz"
                target_patch_path = os.path.join(sha_dir, safe_filename)

                with gzip.open(target_patch_path, "wb") as f_gz:
                    f_gz.write(patch_content.encode("utf-8"))

                # 记录相对 key
                patch_key = f"patches/{repo_id}/{sha}/{safe_filename}"

            db_file = GitCommitFile(
                commit_id=commit_id,
                old_path=old_path,
                new_path=path,
                change_type=change_type,
                is_binary=is_binary,
                additions=add,
                deletions=del_val,
                patch_storage_key=patch_key,
                patch_size_bytes=patch_size,
                patch_truncated=patch_truncated,
            )
            db.add(db_file)

        # 更新 commit 汇总指标
        stmt_update_commit = (
            update(GitCommit)
            .where(GitCommit.id == commit_id)
            .values(files_changed=files_count, additions=additions_total, deletions=deletions_total)
        )
        db.execute(stmt_update_commit)
