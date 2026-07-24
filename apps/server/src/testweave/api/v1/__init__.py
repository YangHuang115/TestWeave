from fastapi import APIRouter

from testweave.api.v1.ai_capabilities import router as ai_capabilities_router
from testweave.api.v1.ai_capability_revision import router as ai_capability_revision_router
from testweave.api.v1.ai_evaluations import router as ai_evaluations_router
from testweave.api.v1.ai_packages import router as ai_packages_router
from testweave.api.v1.ai_releases import router as ai_releases_router
from testweave.api.v1.ai_runs import router as ai_runs_router
from testweave.api.v1.ai_test_design import router as ai_test_design_router
from testweave.api.v1.auth import router as auth_router
from testweave.api.v1.case_modules import router as case_modules_router
from testweave.api.v1.projects import router as projects_router
from testweave.api.v1.repositories import router as repositories_router
from testweave.api.v1.requirements import router as requirements_router
from testweave.api.v1.test_cases import router as test_cases_router
from testweave.api.v1.test_executions import router as test_executions_router
from testweave.api.v1.test_tasks import router as test_tasks_router
from testweave.api.v1.versions import router as versions_router
from testweave.api.v1.workbench import router as workbench_router

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(auth_router)
v1_router.include_router(projects_router)
v1_router.include_router(versions_router)
v1_router.include_router(workbench_router)

v1_router.include_router(requirements_router)
v1_router.include_router(repositories_router)
v1_router.include_router(test_tasks_router)
v1_router.include_router(case_modules_router)
v1_router.include_router(test_cases_router)
v1_router.include_router(ai_capabilities_router)
v1_router.include_router(ai_runs_router)
v1_router.include_router(ai_test_design_router)
v1_router.include_router(ai_capability_revision_router)
v1_router.include_router(test_executions_router)
v1_router.include_router(ai_evaluations_router)
v1_router.include_router(ai_packages_router)
v1_router.include_router(ai_releases_router)
