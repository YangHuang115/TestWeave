from fastapi import APIRouter

from testweave.api.v1.auth import router as auth_router
from testweave.api.v1.projects import router as projects_router
from testweave.api.v1.versions import router as versions_router
from testweave.api.v1.requirements import router as requirements_router
from testweave.api.v1.repositories import router as repositories_router
from testweave.api.v1.test_tasks import router as test_tasks_router
from testweave.api.v1.case_modules import router as case_modules_router
from testweave.api.v1.test_cases import router as test_cases_router

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(auth_router)
v1_router.include_router(projects_router)
v1_router.include_router(versions_router)
v1_router.include_router(requirements_router)
v1_router.include_router(repositories_router)
v1_router.include_router(test_tasks_router)
v1_router.include_router(case_modules_router)
v1_router.include_router(test_cases_router)
