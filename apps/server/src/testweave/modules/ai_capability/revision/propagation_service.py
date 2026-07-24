import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from testweave.db.models import (
    AICapabilityRun,
    AICurrentAcceptedRevisionSet,
)


class PropagationService:
    @staticmethod
    def propagate_upstream_change(
        db: Session,
        run_id: str,
        upstream_node_id: str,
        new_upstream_set_hash: str,
        workflow_dag: dict[str, list[str]],  # node_id -> [downstream_node_ids]
    ) -> list[str]:
        """沿依赖 DAG 拓扑传播上游变更。
        将消费过旧上游的下游 CurrentAcceptedSet 标记为 STALE 并设 rerun_required=True。
        """
        run_uuid = uuid.UUID(str(run_id))
        stale_nodes = []

        # 获取下游受影响节点 (使用 BFS / DFS 遍历)
        visited = set()
        queue = [upstream_node_id]

        while queue:
            curr = queue.pop(0)
            if curr in visited:
                continue
            visited.add(curr)

            downstreams = workflow_dag.get(curr, [])
            for down in downstreams:
                if down not in visited:
                    queue.append(down)
                    # 更新该下游节点的黄金集合指针状态为 STALE
                    stmt = (
                        select(AICurrentAcceptedRevisionSet)
                        .where(
                            AICurrentAcceptedRevisionSet.run_id == run_uuid,
                            AICurrentAcceptedRevisionSet.node_id == down,
                        )
                        .with_for_update()
                    )
                    acc_set = db.scalar(stmt)
                    if acc_set and acc_set.freshness_status != "STALE":
                        acc_set.freshness_status = "STALE"
                        acc_set.rerun_required = True
                        acc_set.state_reasons = {
                            "reason": "UPSTREAM_REVISION_CHANGED",
                            "upstream_node_id": upstream_node_id,
                            "new_upstream_set_hash": new_upstream_set_hash,
                        }
                        stale_nodes.append(down)

        if stale_nodes:
            # 将 Run 状态置为 WAITING_RETRY (只要 Run 处于活动非终态)
            run = db.get(AICapabilityRun, run_uuid)
            if run and run.status not in ("SUCCEEDED", "FAILED", "CANCELLED"):
                run.status = "WAITING_RETRY"

        db.flush()
        return stale_nodes
