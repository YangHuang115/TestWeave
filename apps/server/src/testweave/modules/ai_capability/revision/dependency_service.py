import uuid

from sqlalchemy.orm import Session

from testweave.db.models import AIDependencyEdge


class DependencyService:
    @staticmethod
    def record_dependency_edge(
        db: Session,
        project_id: str,
        run_id: str,
        upstream_node_id: str,
        upstream_set_revision_id: str,
        downstream_node_id: str,
        downstream_context_snapshot_id: str,
        downstream_step_execution_id: str | None = None,
        downstream_output_set_revision_id: str | None = None,
    ) -> AIDependencyEdge:
        edge = AIDependencyEdge(
            project_id=uuid.UUID(str(project_id)),
            run_id=uuid.UUID(str(run_id)),
            upstream_node_id=upstream_node_id,
            upstream_set_revision_id=uuid.UUID(str(upstream_set_revision_id)),
            downstream_node_id=downstream_node_id,
            downstream_context_snapshot_id=uuid.UUID(str(downstream_context_snapshot_id)),
            downstream_step_execution_id=uuid.UUID(str(downstream_step_execution_id))
            if downstream_step_execution_id
            else None,
            downstream_output_set_revision_id=uuid.UUID(str(downstream_output_set_revision_id))
            if downstream_output_set_revision_id
            else None,
        )
        db.add(edge)
        db.flush()
        return edge
