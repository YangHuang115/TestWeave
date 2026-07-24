import re
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from testweave.db.models import GitCommit, Requirement, RequirementCommitLink
from testweave.modules.requirements.service import normalize_requirement_no


class MatcherService:
    @staticmethod
    def extract_requirement_tokens(message: str) -> list[str]:
        if not message:
            return []
        # 正则提取形如 REQ-1001, ABC-1234 等标准格式的单号，保证单词边界
        pattern = re.compile(r"\b([a-zA-Z0-9]+-[0-9]+)\b")
        tokens = pattern.findall(message)
        # 去重并规范化
        return list(set(normalize_requirement_no(t) for t in tokens))

    @classmethod
    def match_commits_to_requirements(
        cls, db: Session, project_id: str, repository_id: str, commit_shas: list[str]
    ) -> int:
        """增量将指定的 commits shas 与项目内的需求单号进行正则解析匹配"""
        if not commit_shas:
            return 0

        # 1. 批量查询 commits
        stmt_commits = select(GitCommit).where(
            GitCommit.repository_id == uuid.UUID(str(repository_id)), GitCommit.sha.in_(commit_shas)
        )
        commits = db.scalars(stmt_commits).all()
        if not commits:
            return 0

        # 2. 拉取项目下所有未归档的需求（以建立内存 mapping 加速）
        stmt_reqs = select(Requirement).where(
            Requirement.project_id == uuid.UUID(str(project_id)), Requirement.status != "ARCHIVED"
        )
        reqs = db.scalars(stmt_reqs).all()
        if not reqs:
            return 0

        req_map = {r.requirement_no_normalized: r for r in reqs}

        links_count = 0
        for c in commits:
            # 提取 Commit message 里的单号
            tokens = cls.extract_requirement_tokens(c.message)
            for tok in tokens:
                if tok in req_map:
                    req = req_map[tok]

                    # 检查是否已有关联
                    stmt_exist = select(RequirementCommitLink).where(
                        RequirementCommitLink.requirement_id == req.id,
                        RequirementCommitLink.commit_id == c.id,
                        RequirementCommitLink.status == "ACTIVE",
                    )
                    existing = db.scalar(stmt_exist)

                    if not existing:
                        link = RequirementCommitLink(
                            project_id=uuid.UUID(str(project_id)),
                            requirement_id=req.id,
                            commit_id=c.id,
                            matched_requirement_no=req.requirement_no,
                            match_revision=1,
                            match_method="COMMIT_MESSAGE_EXACT_TOKEN",
                            status="ACTIVE",
                        )
                        db.add(link)
                        links_count += 1

        db.flush()
        return links_count

    @classmethod
    def rematch_project_requirements(cls, db: Session, project_id: str) -> int:
        """重新对项目下所有 ACTIVE 提交重新执行需求匹配扫描 (常用于手动触发或单号大范围修改)"""
        pid = uuid.UUID(str(project_id))

        # 1. 物理删除已有所有的匹配链接
        stmt_del = delete(RequirementCommitLink).where(RequirementCommitLink.project_id == pid)
        db.execute(stmt_del)
        db.flush()

        # 2. 找出该项目下所有的仓库
        from testweave.modules.repositories.service import RepositoryService

        repo = RepositoryService.get_repository_by_project_id(db, project_id)
        if not repo:
            return 0

        # 3. 找出所有 ACTIVE 的 commits shas 并分批进行重新匹配
        stmt_commits = select(GitCommit.sha).where(GitCommit.repository_id == repo.id)
        shas = list(db.scalars(stmt_commits).all())

        # 分批处理以防 memory 溢出
        batch_size = 500
        total_matched = 0
        for i in range(0, len(shas), batch_size):
            batch = shas[i : i + batch_size]
            total_matched += cls.match_commits_to_requirements(db, project_id, str(repo.id), batch)

        return total_matched

    @classmethod
    def match_single_requirement(
        cls, db: Session, project_id: str, requirement: Requirement
    ) -> int:
        """为单条需求寻找并绑定已同步在库的历史 commits"""
        pid = uuid.UUID(str(project_id))

        # 1. 找出该项目下所有的仓库
        from testweave.modules.repositories.service import RepositoryService

        repo = RepositoryService.get_repository_by_project_id(db, project_id)
        if not repo:
            return 0

        # 2. 批量查出该项目下可能相关的 commits
        stmt_commits = select(GitCommit).where(
            GitCommit.repository_id == repo.id,
            GitCommit.message.ilike(f"%{requirement.requirement_no}%"),
        )
        commits = db.scalars(stmt_commits).all()
        if not commits:
            return 0

        links_count = 0
        for c in commits:
            # 更加精确地双重提取确认词组边界
            tokens = cls.extract_requirement_tokens(c.message)
            if requirement.requirement_no_normalized in tokens:
                # 检查是否已有关联
                stmt_exist = select(RequirementCommitLink).where(
                    RequirementCommitLink.requirement_id == requirement.id,
                    RequirementCommitLink.commit_id == c.id,
                    RequirementCommitLink.status == "ACTIVE",
                )
                existing = db.scalar(stmt_exist)

                if not existing:
                    link = RequirementCommitLink(
                        project_id=pid,
                        requirement_id=requirement.id,
                        commit_id=c.id,
                        matched_requirement_no=requirement.requirement_no,
                        match_revision=1,
                        match_method="COMMIT_MESSAGE_EXACT_TOKEN",
                        status="ACTIVE",
                    )
                    db.add(link)
                    links_count += 1

        db.flush()
        return links_count
