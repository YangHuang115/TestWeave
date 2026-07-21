# 统一权限码定义
PROJECT_READ = "project.read"
PROJECT_UPDATE = "project.update"
PROJECT_MEMBER_MANAGE = "project.member.manage"
VERSION_READ = "version.read"
VERSION_MANAGE = "version.manage"
TASK_READ = "task.read"
TASK_MANAGE = "task.manage"
TEST_CASE_READ = "test_case.read"
TEST_CASE_MANAGE = "test_case.manage"
DEFECT_READ = "defect.read"
DEFECT_MANAGE = "defect.manage"
REPORT_READ = "report.read"
AGENT_USE = "agent.use"
AGENT_MANAGE = "agent.manage"
ADMIN_READ = "admin.read"
ADMIN_MANAGE = "admin.manage"

# 内置角色与权限码集合映射
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "project_admin": {
        PROJECT_READ,
        PROJECT_UPDATE,
        PROJECT_MEMBER_MANAGE,
        VERSION_READ,
        VERSION_MANAGE,
        TASK_READ,
        TASK_MANAGE,
        TEST_CASE_READ,
        TEST_CASE_MANAGE,
        DEFECT_READ,
        DEFECT_MANAGE,
        REPORT_READ,
        AGENT_USE,
        AGENT_MANAGE,
        ADMIN_READ,
        ADMIN_MANAGE,
    },
    "test_lead": {
        PROJECT_READ,
        VERSION_READ,
        VERSION_MANAGE,
        TASK_READ,
        TASK_MANAGE,
        TEST_CASE_READ,
        TEST_CASE_MANAGE,
        DEFECT_READ,
        DEFECT_MANAGE,
        REPORT_READ,
        AGENT_USE,
        AGENT_MANAGE,
    },
    "test_member": {
        PROJECT_READ,
        VERSION_READ,
        TASK_READ,
        TASK_MANAGE,
        TEST_CASE_READ,
        TEST_CASE_MANAGE,
        DEFECT_READ,
        DEFECT_MANAGE,
        REPORT_READ,
        AGENT_USE,
    },
}


def get_permissions_for_role(role_id: str) -> set[str]:
    """根据内置角色 ID 获取对应的权限集合"""
    return ROLE_PERMISSIONS.get(role_id, set())
