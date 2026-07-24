from typing import Any

from testweave.core.errors import AppError
from testweave.modules.ai_capability.enums import ExecNodeType
from testweave.modules.ai_capability.runtime.input_mapping import InputMappingDSL


class WorkflowGraph:
    """Workflow DAG 拓扑结构与计算节点调度解析器"""

    def __init__(self, workflow_snapshot: dict[str, Any]) -> None:
        self.raw_workflow = workflow_snapshot
        self.nodes: dict[str, dict[str, Any]] = {}
        self.dependencies: dict[str, set[str]] = {}
        self.dependents: dict[str, set[str]] = {}
        self._parse_and_validate()

    def _parse_and_validate(self) -> None:
        raw_nodes = self.raw_workflow.get("nodes")
        if not isinstance(raw_nodes, dict) or not raw_nodes:
            raise AppError(
                code="RUN_CAPABILITY_NOT_RUNNABLE",
                message="Workflow 快照中缺少有效的 nodes 节点定义",
                status_code=400,
            )

        supported_types = {t.value for t in ExecNodeType}

        for node_id, node_def in raw_nodes.items():
            if not isinstance(node_def, dict):
                raise AppError(
                    code="RUN_CAPABILITY_NOT_RUNNABLE",
                    message=f"节点 '{node_id}' 定义格式无效",
                    status_code=400,
                )
            node_type = node_def.get("type", "").upper()
            if node_type not in supported_types:
                raise AppError(
                    code="RUN_CAPABILITY_NOT_RUNNABLE",
                    message=f"节点 '{node_id}' 包含了 P2 不支持的执行节点类型 '{node_type}'",
                    status_code=400,
                )
            self.nodes[node_id] = node_def
            self.dependencies[node_id] = set()
            self.dependents[node_id] = set()

        # 解析引用产生依赖边
        for node_id, node_def in self.nodes.items():
            input_def = node_def.get("input")
            refs = self._extract_refs(input_def)
            for ref_str in refs:
                source_key, _ = InputMappingDSL.parse_reference(ref_str)
                if source_key.endswith(".output"):
                    dep_node_id = source_key[:-7]
                    if dep_node_id not in self.nodes:
                        raise AppError(
                            code="RUN_CAPABILITY_NOT_RUNNABLE",
                            message=f"节点 '{node_id}' 引用了不存在的上游节点 '{dep_node_id}'",
                            status_code=400,
                        )
                    if dep_node_id == node_id:
                        raise AppError(
                            code="RUN_CAPABILITY_NOT_RUNNABLE",
                            message=f"节点 '{node_id}' 不能依赖自身",
                            status_code=400,
                        )
                    self.dependencies[node_id].add(dep_node_id)
                    self.dependents[dep_node_id].add(node_id)

        # 检查拓扑环与连通性
        self._check_cycles()

        # 校验有且仅有一个最终输出节点
        sink_nodes = [nid for nid, deps in self.dependents.items() if not deps]
        if len(sink_nodes) != 1:
            msg = f"Workflow 终端节点必须唯一，当前存在 {len(sink_nodes)} 个: {sink_nodes}"
            raise AppError(
                code="RUN_CAPABILITY_NOT_RUNNABLE",
                message=msg,
                status_code=400,
            )
        self.sink_node_id = sink_nodes[0]

    def _extract_refs(self, val: Any) -> list[str]:
        refs = []
        if isinstance(val, str):
            refs.append(val)
        elif isinstance(val, dict):
            for v in val.values():
                refs.extend(self._extract_refs(v))
        elif isinstance(val, list):
            for item in val:
                refs.extend(self._extract_refs(item))
        return refs

    def _check_cycles(self) -> None:
        in_degree = {nid: len(deps) for nid, deps in self.dependencies.items()}
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        visited_count = 0

        while queue:
            curr = queue.pop(0)
            visited_count += 1
            for dependent in self.dependents[curr]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if visited_count != len(self.nodes):
            raise AppError(
                code="RUN_CAPABILITY_NOT_RUNNABLE",
                message="Workflow 存在循环依赖，无法构成 DAG 拓扑",
                status_code=400,
            )

    def get_ancestors(self, node_id: str) -> set[str]:
        """获取指定节点的所有祖先节点 ID 集合"""
        ancestors = set()
        queue = list(self.dependencies.get(node_id, set()))
        while queue:
            curr = queue.pop(0)
            if curr not in ancestors:
                ancestors.add(curr)
                queue.extend(list(self.dependencies.get(curr, set())))
        return ancestors

    def get_runnable_nodes(
        self, completed_node_ids: set[str], pending_node_ids: set[str]
    ) -> list[str]:
        """判定当前所有依赖均已 SUCCEEDED 且当前仍处于 PENDING 状态的就绪节点"""
        runnable = []
        for nid in pending_node_ids:
            deps = self.dependencies.get(nid, set())
            if deps.issubset(completed_node_ids):
                runnable.append(nid)
        return runnable
