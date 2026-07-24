import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.core.errors import AppError
from testweave.db.models import (
    AICapability,
    AICapabilityPackage,
    AICapabilityVersion,
)
from testweave.modules.ai_capability.schemas import (
    FileMapping,
)


# --- 限制性 YAML 解析器防止重 key 和锚点/别名注入 (Billion Laughs) ---
class SafeNoDuplicatesLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in mapping:
                raise yaml.constructor.ConstructorError(
                    None, None, f"检测到重复的 YAML 键: {key}", key_node.start_mark
                )
            value = self.construct_object(value_node, deep=deep)
            mapping[key] = value
        return super().construct_mapping(node, deep=deep)

    def compose_node(self, parent, index):
        # 拦截 Anchor/Alias 节点以规避 Billion Laughs 漏洞
        if self.check_event(yaml.AliasEvent):
            raise yaml.composer.ComposerError(
                "YAML 解析安全拦截：禁止在能力包中使用锚点/别名(Aliases)"
            )
        return super().compose_node(parent, index)


def safe_yaml_load(content: str) -> Any:
    """安全的 YAML 解析器"""
    return yaml.load(content, Loader=SafeNoDuplicatesLoader)


class SyncService:
    @staticmethod
    def validate_capability_package(
        token: Any,
        files: list[FileMapping],
    ) -> dict[str, Any]:
        issues = []
        valid = True
        syncable = True
        package_fingerprint = None
        compatibility_level = None
        workflow_snap = None
        input_schema_snap = None
        output_schema_snap = None
        cap_config = None

        # 1. 物理层限制校验
        if not files:
            issues.append("能力包文件不能为空")
            return {"valid": False, "syncable": False, "issues": issues}

        if len(files) > 128:
            issues.append("文件总数超出 128 个限制")
            valid = False
            syncable = False

        total_size = 0
        for f in files:
            content_bytes = f.content.encode("utf-8")
            file_size = len(content_bytes)
            total_size += file_size

            if file_size > 1024 * 1024:
                issues.append(f"文件 {f.path} 超过单文件 1 MiB 限制")
                valid = False
                syncable = False

            # 相对路径格式校验
            path_str = f.path.strip()
            if path_str.startswith("/") or ".." in path_str or "\\" in path_str:
                issues.append(f"文件路径 {f.path} 格式非法（禁止绝对路径或跨目录/斜杠问题）")
                valid = False
                syncable = False

            if len(path_str) > 240:
                issues.append(f"文件路径 {f.path} 长度超出 240 字符")
                valid = False
                syncable = False

            # 目录深度校验
            depth = len([part for part in path_str.split("/") if part]) - 1
            if depth > 12:
                issues.append(f"文件路径 {f.path} 目录深度超过 12 层")
                valid = False
                syncable = False

        if total_size > 5 * 1024 * 1024:
            issues.append("能力包总大小超出 5 MiB 限制")
            valid = False
            syncable = False

        # 文件映射构建
        file_map = {f.path: f.content for f in files}

        # 2. manifest.lock 哈希校验
        if "manifest.lock" not in file_map:
            issues.append("能力包缺失 manifest.lock 文件")
            return {"valid": False, "syncable": False, "issues": issues}

        try:
            lock_data = json.loads(file_map["manifest.lock"])
            lock_files = lock_data.get("files", {})
        except Exception as exc:
            issues.append(f"解析 manifest.lock JSON 失败: {exc!s}")
            return {"valid": False, "syncable": False, "issues": issues}

        # 逐个检查 manifest 声明
        for rel_path, expected_sha in lock_files.items():
            if not expected_sha.startswith("sha256:"):
                issues.append(f"manifest.lock 中文件 {rel_path} 的哈希协议不支持: {expected_sha}")
                valid = False
                syncable = False
                continue

            expected_hash = expected_sha[7:]
            if rel_path not in file_map:
                issues.append(f"manifest.lock 声明的文件 {rel_path} 缺失")
                valid = False
                syncable = False
                continue

            content_bytes = file_map[rel_path].encode("utf-8")
            actual_hash = hashlib.sha256(content_bytes).hexdigest()
            if actual_hash != expected_hash:
                issues.append(f"文件 {rel_path} 的哈希值不匹配")
                valid = False
                syncable = False

        # 检查多余文件（不包括 manifest.lock）
        for rel_path in file_map:
            if rel_path != "manifest.lock" and rel_path not in lock_files:
                issues.append(f"文件 {rel_path} 未在 manifest.lock 中声明")
                valid = False
                syncable = False

        # 指纹生成：对所有文件的路径排序，拼接其内容哈希后再哈希
        fingerprint_ctx = hashlib.sha256()
        for rel_path in sorted(file_map.keys()):
            fingerprint_ctx.update(f"{rel_path}:{file_map[rel_path]}".encode())
        package_fingerprint = fingerprint_ctx.hexdigest()

        # 如果基础格式不满足，不再做深层逻辑校验
        if not syncable:
            return {
                "valid": False,
                "syncable": False,
                "issues": issues,
                "packageFingerprint": package_fingerprint,
            }

        # 3. capability.yaml 解析与安全校验
        if "capability.yaml" not in file_map:
            issues.append("能力包缺失 capability.yaml 配置文件")
            return {"valid": False, "syncable": False, "issues": issues}

        try:
            cap_config = safe_yaml_load(file_map["capability.yaml"])
        except Exception as exc:
            issues.append(f"安全解析 capability.yaml 失败: {exc!s}")
            return {"valid": False, "syncable": False, "issues": issues}

        # 校验 capability.yaml 的 schema
        cap_info = cap_config.get("capability") if cap_config else None
        if not cap_config or not cap_info:
            issues.append("capability.yaml 结构非法，缺少 capability 节点")
            return {"valid": False, "syncable": False, "issues": issues}

        protocol_version = cap_config.get("protocol_version")
        if protocol_version != "1.0":
            issues.append("不合法的协议版本 (protocol_version 必须为 1.0)")
            valid = False
            syncable = False

        cap_id = cap_info.get("id")
        cap_version = cap_info.get("version")
        cap_name = cap_info.get("name")
        compatibility_level = cap_info.get("compatibility_level")

        if not cap_id or not cap_version or not cap_name or not compatibility_level:
            issues.append("capability 缺少 id, version, name 或 compatibility_level")
            valid = False
            syncable = False

        # 校验命名空间授权权限
        if cap_id:
            # 校验命名空间规则：只能是 testweave/* 或 project/{project_id}/*
            # 格式：testweave/code 或 project/{project_uuid}/code
            parts = cap_id.split("/")
            if len(parts) < 2:
                issues.append("不合法的 capability ID 格式，必须包含命名空间")
                valid = False
                syncable = False
            else:
                namespace = "/".join(parts[:-1])
                parts[-1]

                # 官方 Token 具有 testweave/*，可以同步 testweave/{code}
                # 或 project/{project_uuid}/{code}
                # 项目 Token 只能同步 project/{project_id}/{code}
                allowed_scope = token.namespace_scope
                if allowed_scope == "*":
                    pass  # 完全授权
                elif allowed_scope == "testweave/*":
                    if namespace != "testweave" and not namespace.startswith("project/"):
                        issues.append(f"令牌作用域 {allowed_scope} 拒绝写入命名空间 {namespace}")
                        valid = False
                        syncable = False
                elif allowed_scope.startswith("project/"):
                    project_uuid_str = allowed_scope.split("/")[-1]
                    if namespace != f"project/{project_uuid_str}":
                        issues.append(
                            f"令牌作用域限制在 project/{project_uuid_str}，拒绝写入 {namespace}"
                        )
                        valid = False
                        syncable = False
                else:
                    if namespace != allowed_scope:
                        issues.append(f"令牌作用域 {allowed_scope} 拒绝写入命名空间 {namespace}")
                        valid = False
                        syncable = False

        # 4. Schema 存在性及语法校验
        input_schema_path = cap_info.get("input_schema") if cap_info else None
        output_schema_path = cap_info.get("output_schema") if cap_info else None

        if input_schema_path:
            if input_schema_path not in file_map:
                issues.append(f"声明的 input_schema 文件 {input_schema_path} 缺失")
                valid = False
                syncable = False
            else:
                try:
                    input_schema_snap = json.loads(file_map[input_schema_path])
                except Exception as exc:
                    issues.append(f"input_schema 不是合法的 JSON: {exc!s}")
                    valid = False
                    syncable = False

        if output_schema_path:
            if output_schema_path not in file_map:
                issues.append(f"声明的 output_schema 文件 {output_schema_path} 缺失")
                valid = False
                syncable = False
            else:
                try:
                    output_schema_snap = json.loads(file_map[output_schema_path])
                except Exception as exc:
                    issues.append(f"output_schema 不是合法的 JSON: {exc!s}")
                    valid = False
                    syncable = False

        # 5. Workflow DAG 拓扑校验
        workflow_entry = cap_config.get("workflow_entry")
        if not workflow_entry:
            issues.append("capability.yaml 缺少 workflow_entry 路径声明")
            valid = False
            syncable = False
        elif workflow_entry not in file_map:
            issues.append(f"声明的 workflow_entry 文件 {workflow_entry} 缺失")
            valid = False
            syncable = False
        else:
            try:
                workflow_snap = safe_yaml_load(file_map[workflow_entry])
                if not workflow_snap or not isinstance(workflow_snap, dict):
                    issues.append("Workflow 结构必须是一个 YAML 对象")
                    valid = False
                    syncable = False
                else:
                    nodes = workflow_snap.get("nodes", [])
                    edges = workflow_snap.get("edges", [])

                    if not isinstance(nodes, list) or not isinstance(edges, list):
                        issues.append("Workflow 中 nodes 和 edges 必须为数组")
                        valid = False
                        syncable = False
                    else:
                        node_ids = set()
                        node_map = {}
                        for idx, node in enumerate(nodes):
                            if not isinstance(node, dict) or "id" not in node:
                                issues.append(f"Workflow 节点索引 {idx} 缺少 id 字段")
                                valid = False
                                syncable = False
                                continue
                            nid = node["id"]
                            if nid in node_ids:
                                issues.append(f"Workflow 节点 ID 重复: {nid}")
                                valid = False
                                syncable = False
                            node_ids.add(nid)
                            node_map[nid] = node

                            # Node Transform & Validator 校验白名单
                            node.get("type")
                            transform = node.get("transform")
                            validator = node.get("validator")

                            if transform:
                                # transform 白名单
                                allowed_transforms = {
                                    "human-confirmation",
                                    "test-point-generation",
                                    "requirement-modeling",
                                    "test-point-validation",
                                }
                                if transform not in allowed_transforms:
                                    issues.append(
                                        f"节点 {nid} 声明了未授权的 transform: {transform}"
                                    )
                                    valid = False
                                    syncable = False

                            if validator:
                                # 校验 validator 声明是否合规（例如只能是
                                # 相对路径存在的 schema json 或是内建名称）
                                if not validator.endswith(".json") and validator not in [
                                    "requirement-model"
                                ]:
                                    issues.append(
                                        f"节点 {nid} 声明了不合法的 validator 标识: {validator}"
                                    )
                                    valid = False
                                    syncable = False
                                elif validator.endswith(".json") and validator not in file_map:
                                    issues.append(
                                        f"节点 {nid} 关联的 validator 架构文件 {validator} 缺失"
                                    )
                                    valid = False
                                    syncable = False

                        # 边校验及 DAG 环路检测
                        adj_list: dict[str, list[str]] = {nid: [] for nid in node_ids}
                        in_degree = {nid: 0 for nid in node_ids}
                        edge_pairs = set()

                        for idx, edge in enumerate(edges):
                            if (
                                not isinstance(edge, dict)
                                or "source" not in edge
                                or "target" not in edge
                            ):
                                issues.append(f"Workflow 边索引 {idx} 缺少 source 或 target")
                                valid = False
                                syncable = False
                                continue
                            u = edge["source"]
                            v = edge["target"]

                            if u not in node_ids:
                                issues.append(f"边 {u} -> {v} 的起始节点不存在")
                                valid = False
                                syncable = False
                                continue
                            if v not in node_ids:
                                issues.append(f"边 {u} -> {v} 的终止节点不存在")
                                valid = False
                                syncable = False
                                continue

                            if u == v:
                                issues.append(f"Workflow 检测到自环: {u} -> {v}")
                                valid = False
                                syncable = False
                                continue

                            pair = (u, v)
                            if pair in edge_pairs:
                                issues.append(f"Workflow 重复边声明: {u} -> {v}")
                                valid = False
                                syncable = False
                                continue
                            edge_pairs.add(pair)

                            adj_list[u].append(v)
                            in_degree[v] += 1

                        # Kahn 算法环路检测
                        if valid and syncable and node_ids:
                            queue = [nid for nid in node_ids if in_degree[nid] == 0]
                            visited_count = 0
                            while queue:
                                curr = queue.pop(0)
                                visited_count += 1
                                for neighbor in adj_list[curr]:
                                    in_degree[neighbor] -= 1
                                    if in_degree[neighbor] == 0:
                                        queue.append(neighbor)
                            if visited_count < len(node_ids):
                                issues.append("Workflow 结构含有循环依赖（检测到环）")
                                valid = False
                                syncable = False

                        # 孤立节点及单一连通性校验
                        if valid and syncable and len(node_ids) > 1:
                            # 孤立节点校验
                            connected_nodes = set()
                            for u, v in edge_pairs:
                                connected_nodes.add(u)
                                connected_nodes.add(v)
                            isolated = node_ids - connected_nodes
                            if isolated:
                                issues.append(f"检测到未连接的孤立节点: {list(isolated)}")
                                valid = False
                                syncable = False

                            # 单一连通性：构建无向邻接表，判断连通分量是否为 1
                            undirected_adj: dict[str, list[str]] = {nid: [] for nid in node_ids}
                            for u, v in edge_pairs:
                                undirected_adj[u].append(v)
                                undirected_adj[v].append(u)

                            # BFS 遍历
                            bfs_visited = set()
                            start_node = next(iter(node_ids))
                            bfs_queue = [start_node]
                            bfs_visited.add(start_node)
                            while bfs_queue:
                                curr = bfs_queue.pop(0)
                                for neighbor in undirected_adj[curr]:
                                    if neighbor not in bfs_visited:
                                        bfs_visited.add(neighbor)
                                        bfs_queue.append(neighbor)

                            if len(bfs_visited) < len(node_ids):
                                issues.append("Workflow 含有多连通分量，存在孤立子图")
                                valid = False
                                syncable = False

            except Exception as exc:
                issues.append(f"解析 Workflow 失败: {exc!s}")
                valid = False
                syncable = False

        return {
            "valid": valid,
            "syncable": syncable,
            "issues": issues,
            "packageFingerprint": package_fingerprint,
            "compatibilityLevel": compatibility_level,
            "workflowSnapshot": workflow_snap,
            "inputSchema": input_schema_snap,
            "outputSchema": output_schema_snap,
            "capConfig": cap_config,
            "filesSnapshot": {"files": [{"path": f.path, "content": f.content} for f in files]},
        }

    @staticmethod
    def sync_capability_package(
        db: Session,
        token: Any,
        files: list[FileMapping],
    ) -> tuple[dict[str, Any], AICapabilityVersion | None]:
        # 1. 验证
        report = SyncService.validate_capability_package(token, files)
        if not report["syncable"] or not report["valid"]:
            return report, None

        cap_config = report["capConfig"]
        cap_info = cap_config["capability"]
        cap_id = cap_info["id"]
        cap_version = cap_info["version"]
        cap_name = cap_info["name"]
        compatibility_level = report["compatibilityLevel"]

        parts = cap_id.split("/")
        namespace = "/".join(parts[:-1])
        code = parts[-1]

        # 2. 写 AICapability 表
        stmt = select(AICapability).where(
            AICapability.namespace == namespace, AICapability.code == code
        )
        capability = db.scalar(stmt)

        scope = "OFFICIAL" if namespace == "testweave" else "PROJECT"
        project_id = None if scope == "OFFICIAL" else token.project_id

        if not capability:
            capability = AICapability(
                id=uuid.uuid4(),
                namespace=namespace,
                code=code,
                name=cap_name,
                category=cap_info.get("category", "OTHER"),
                scope=scope,
                project_id=project_id,
                status="ACTIVE",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            db.add(capability)
            db.flush()
        else:
            # 跨项目安全防范：如果在 PROJECT scope，只允许修改自身项目的，不能越权修改其他项目
            if capability.scope == "PROJECT" and capability.project_id != token.project_id:
                raise AppError(
                    code="CAPABILITY_ACCESS_DENIED",
                    message="拒绝修改其他项目的能力包",
                    status_code=403,
                )
            capability.name = cap_name
            capability.category = cap_info.get("category", "OTHER")
            capability.updated_at = datetime.now(UTC)

        # 3. 写 AICapabilityVersion 表，检验版本号
        stmt_ver = select(AICapabilityVersion).where(
            AICapabilityVersion.capability_id == capability.id,
            AICapabilityVersion.version == cap_version,
        )
        existing_version = db.scalar(stmt_ver)

        if existing_version:
            if existing_version.status == "SYNCED_DRAFT":
                # 可以覆盖
                db.delete(existing_version)
                db.flush()
            else:
                report["valid"] = False
                report["syncable"] = False
                report["issues"].append(f"版本号 {cap_version} 在该能力包下已存在且处于非草稿状态")
                return report, None

        # 4. 创建新版本
        version_entity = AICapabilityVersion(
            id=uuid.uuid4(),
            capability_id=capability.id,
            version=cap_version,
            status="SYNCED_DRAFT",
            package_fingerprint=report["packageFingerprint"],
            compatibility_level=compatibility_level,
            workflow_snapshot=report["workflowSnapshot"],
            input_schema=report["inputSchema"],
            output_schema=report["outputSchema"],
            created_source="GATEWAY_SYNC",
            created_by=token.created_by_id,
            created_at=datetime.now(UTC),
        )
        db.add(version_entity)
        db.flush()

        # 5. 创建 AICapabilityPackage 实体
        pkg_entity = AICapabilityPackage(
            id=uuid.uuid4(),
            capability_version_id=version_entity.id,
            package_fingerprint=report["packageFingerprint"],
            validation_report={
                "valid": report["valid"],
                "syncable": report["syncable"],
                "packageFingerprint": report["packageFingerprint"],
                "issues": report["issues"],
            },
            files_snapshot=report["filesSnapshot"],
            created_at=datetime.now(UTC),
        )
        db.add(pkg_entity)
        db.flush()

        return report, version_entity
