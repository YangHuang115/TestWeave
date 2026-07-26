# TestWeave

TestWeave 是一个 AI 原生测试设计与测试资产管理平台。它把项目、版本、需求、测试任务、测试点、用例、执行记录和 Agent Run 放在同一条可追溯工作流中，让 AI 负责生成候选结果，由用户负责确认和发布正式测试资产。

> 当前仓库处于持续开发阶段，可用于本地开发、功能验证和需求评审，尚未形成生产部署方案。

## 核心工作流

```text
项目与版本
  → 需求与附件
  → 用例设计任务
  → AI 需求分析与测试点
  → 候选用例与人工审核
  → 项目用例库
  → 测试执行、结果与证据
```

平台坚持三个边界：

- AI 只产生结构化候选资产，不绕过人工审核直接发布；
- PostgreSQL 中的业务对象和修订是正式事实，检索结果和模型输出不是；
- 页面、REST API 和外接 Agent 复用同一套权限与业务规则。

## 当前仓库能力

| 能力域      | 当前代码状态                                                                   |
| ----------- | ------------------------------------------------------------------------------ |
| 平台基础    | 登录会话、CSRF、防越权项目上下文、成员角色、项目归档、审计事件和统一错误模型   |
| 个人工作台  | 已有概要、待办、进行中任务、Agent Run 和最近访问基础聚合，交互闭环仍在完善     |
| 版本与需求  | 版本管理、需求详情、附件、需求版本关系、Git 仓库配置与 Diff 查询               |
| 测试任务    | 用例设计/执行任务、需求范围、负责人、参与人、状态流转和活动时间线              |
| AI 测试设计 | 需求分析、测试点、候选用例、审核阶段以及 Revision/反馈流程                     |
| 用例库      | 用例模块树、表格式编辑、修订历史和任务思维导图                                 |
| 测试执行    | 固定用例快照、执行记录、批量通过、证据、完成校验和 Excel 导出                  |
| AI 能力中心 | Capability、Run、评测、优化包、发布、灰度与回滚相关接口和页面                  |
| 外接 Agent  | 无状态 `/external/v1` Gateway API、Token Scope、候选结果提交和独立客户端工作区 |
| 缺陷与报告  | 当前仅有页面占位，完整业务闭环尚未实现                                         |

产品目标与当前实现不是同一概念。完整产品边界见[项目概览](docs/project/overview.md)和[项目范围](docs/project/scope.md)；易变的实现进度应结合[当前状态](docs/status/current-state.md)、代码和实际测试结果判断。

## 技术架构

```text
Vue 3 / TypeScript / Vite
            ↓
 FastAPI / Pydantic / SQLAlchemy
            ↓
 PostgreSQL 17 / Alembic / 本地对象存储
```

- Web：Vue 3、Vue Router、Pinia、TypeScript、Vite、Vitest、Playwright；
- Server：Python 3.12+、FastAPI、Pydantic v2、SQLAlchemy 2、Alembic、psycopg 3；
- Quality：Ruff、mypy、ESLint、Prettier、pytest、GitHub Actions；
- AI：版本化 Capability、Run、Revision、评测与无状态 External Agent Gateway。

## 快速开始

### 1. 环境要求

- Node.js `22.13+`（22 LTS）或 Node.js 24；
- npm 10–11；
- Python 3.12–3.13；
- [uv](https://docs.astral.sh/uv/)；
- Docker Desktop 或兼容的 Docker Compose 环境。

### 2. 安装并初始化数据库

```bash
cp .env.example .env
make setup
make db-up
make migrate
```

`.env.example` 仅提供本地开发占位值。若修改 `POSTGRES_PASSWORD`，需同步修改 `TESTWEAVE_DATABASE_URL` 中的密码。

### 3. 创建首个系统管理员

```bash
uv run --project apps/server \
  python apps/server/src/testweave/cli.py create-admin \
  --username admin \
  --email admin@example.com \
  --display-name 管理员
```

命令会交互式要求输入并确认管理员密码。

### 4. 启动应用

分别在两个终端运行：

```bash
make server
```

```bash
make web
```

启动后可访问：

- Web：`http://127.0.0.1:5173`
- OpenAPI：`http://127.0.0.1:8000/api/docs`（非生产环境）
- 存活检查：`http://127.0.0.1:8000/health/live`
- 就绪检查：`http://127.0.0.1:8000/health/ready`

Vite 默认把 `/api` 和 `/health` 代理到本地服务端，因此本地开发通常无需设置 `VITE_API_BASE_URL`。

## 常用命令

| 命令                           | 用途                                      |
| ------------------------------ | ----------------------------------------- |
| `make setup`                   | 按锁文件安装前后端依赖                    |
| `make doctor`                  | 检查 Docker、uv、Node、端口和数据库       |
| `make db-up`                   | 启动本地 PostgreSQL                       |
| `make db-down`                 | 停止数据库并保留数据卷                    |
| `make migrate`                 | 升级到最新 Alembic 迁移                   |
| `make server`                  | 启动 FastAPI 开发服务                     |
| `make web`                     | 启动 Vue/Vite 开发服务                    |
| `make check-server`            | 运行服务端 lint、格式、类型检查和单元测试 |
| `make check-web`               | 运行前端格式、lint、测试和构建            |
| `make check`                   | 运行前后端主要质量门禁                    |
| `make test-server-integration` | 使用一次性 PostgreSQL 运行服务端集成测试  |
| `make test-e2e`                | 启动前后端并运行 Playwright 浏览器旅程    |

安全提示：

- `make reset-db` 会销毁本地数据库数据卷，只在明确需要清空开发数据时使用；
- `make test-e2e` 会向当前本地开发数据库写入合成账号和项目数据；
- 不要把 `TESTWEAVE_TEST_DATABASE_URL` 指向开发库或生产库，集成测试包含迁移升级与降级验证。

## 配置与安全

- 根目录 `.env` 是本地运行配置，不得提交；
- 服务端配置使用 `TESTWEAVE_` 前缀，客户端公开构建配置使用 `VITE_` 前缀；
- 生产环境必须使用至少 32 字符的高熵 `TESTWEAVE_SECRET_KEY`；
- 数据库密码、Cookie、Access Token、Provider 密钥和仓库凭证不得写入代码、文档或日志；
- SSH Git 仓库通过 `TESTWEAVE_GIT_KNOWN_HOSTS_FILE` 指向受信任的 `known_hosts`，不得关闭主机密钥校验；
- PostgreSQL 的本地 Compose 端口默认只绑定 `127.0.0.1`。

## 仓库结构

```text
apps/
├─ web/                     Vue 3 Web 客户端
└─ server/                  FastAPI 服务端、领域模块与 Alembic
packages/
├─ ui/                      前端共享组件
├─ shared/                  稳定共享类型与工具
└─ config/                  公共配置
docs/
├─ project/                 产品定位、范围、路线和术语
├─ architecture/            架构、数据模型和 API 契约
├─ features/                模块需求、设计、计划与验收
├─ standards/               长期工程规范
├─ workflow/                开发流程与交付模板
├─ decisions/               ADR
└─ status/                  当前状态与已知问题
tests/
├─ e2e/                     Playwright 端到端测试
└─ ai-evaluation/           AI 评估资产
external_agent_workspace/   零第三方依赖的外接 Agent 客户端
tools/                      外接 Agent Runner 等开发工具
skills/                     TestWeave Skill 模板与示例
```

## 文档入口

- 开发与智能体规范：[AGENTS.md](AGENTS.md)
- 完整文档中心：[docs/README.md](docs/README.md)
- 项目概览：[docs/project/overview.md](docs/project/overview.md)
- 模块与需求索引：[docs/project/00-模块划分与需求文档索引.md](docs/project/00-模块划分与需求文档索引.md)
- 架构概览：[docs/architecture/overview.md](docs/architecture/overview.md)
- API 契约：[docs/architecture/api-contract.md](docs/architecture/api-contract.md)
- 当前仓库状态：[docs/status/current-state.md](docs/status/current-state.md)
- 统一开发流程：[docs/workflow/development-process.md](docs/workflow/development-process.md)
- 外接 Agent 使用说明：[external_agent_workspace/README.md](external_agent_workspace/README.md)

开始修改前先阅读 `AGENTS.md`，并为任务建立对应的 `REQ-xxxxx`、独立分支和可验证的验收标准。没有实际运行的测试不得标记为通过。
