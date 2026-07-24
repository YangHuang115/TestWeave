"""M09 P3 AI Capability Revision Module Services."""

from testweave.modules.ai_capability.revision.acceptance_service import AcceptanceService
from testweave.modules.ai_capability.revision.artifact_service import ArtifactService
from testweave.modules.ai_capability.revision.canonical_json import (
    calculate_canonical_hash,
    canonicalize_json,
)
from testweave.modules.ai_capability.revision.context_service import ContextService
from testweave.modules.ai_capability.revision.dependency_service import DependencyService
from testweave.modules.ai_capability.revision.diff_service import DiffService
from testweave.modules.ai_capability.revision.feedback_service import FeedbackService
from testweave.modules.ai_capability.revision.field_lock_service import FieldLockService
from testweave.modules.ai_capability.revision.fingerprint import calculate_input_fingerprint
from testweave.modules.ai_capability.revision.projection import (
    extract_items_from_output,
    generate_item_stable_key,
    get_value_by_json_pointer,
    parse_json_pointer,
)
from testweave.modules.ai_capability.revision.propagation_service import PropagationService
from testweave.modules.ai_capability.revision.regeneration_service import RegenerationService
from testweave.modules.ai_capability.revision.set_revision_service import SetRevisionService

__all__ = [
    "AcceptanceService",
    "ArtifactService",
    "ContextService",
    "DependencyService",
    "DiffService",
    "FeedbackService",
    "FieldLockService",
    "PropagationService",
    "RegenerationService",
    "SetRevisionService",
    "calculate_canonical_hash",
    "calculate_input_fingerprint",
    "canonicalize_json",
    "extract_items_from_output",
    "generate_item_stable_key",
    "get_value_by_json_pointer",
    "parse_json_pointer",
]
