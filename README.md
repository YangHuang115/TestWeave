# TestWeave

TestWeave 是一个面向测试设计与测试资产管理的开源平台。当前公开版本提供可本地运行的演示环境，包含用户登录、项目与成员管理、版本与需求管理、代码仓库同步、测试任务、用例模块和测试用例等基础能力。

> 当前版本用于本地体验和开发验证，不建议直接用于生产环境。

## 环境要求

- Node.js 22.13+（22 LTS）或 Node.js 24
- npm 10–11
- Python 3.12–3.13
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop 或兼容的 Docker Compose 环境

## 本地启动

复制本地配置并安装依赖：

```bash
cp .env.example .env
make setup
```

启动 PostgreSQL 并执行数据库迁移：

```bash
make db-up
make migrate
```

创建首个管理员账号。命令会提示你输入密码，密码不会显示在终端中：

```bash
uv run --project apps/server python -m testweave.cli create-admin \
  --username admin \
  --email admin@example.com \
  --display-name Administrator
```

分别在两个终端启动服务端和客户端：

```bash
make server
```

```bash
make web
```

启动后访问：

- 客户端：<http://127.0.0.1:5173>
- OpenAPI：<http://127.0.0.1:8000/api/docs>
- 存活检查：<http://127.0.0.1:8000/health/live>
- 就绪检查：<http://127.0.0.1:8000/health/ready>

停止本地数据库但保留数据：

```bash
make db-down
```

## 基础测试

```bash
make test-server
npm run test:web
```

仓库同时保留了更严格的静态检查和集成测试配置；当前公开快照仍有部分已知质量门禁欠账，不能把 `make check` 的结果等同于基础功能是否可本地启动。

## 配置说明

- 本地配置从仓库根目录的 `.env` 读取，`.env.example` 仅提供开发示例值。
- 服务端配置使用 `TESTWEAVE_` 前缀。
- 客户端公开构建配置使用 `VITE_` 前缀。
- 请勿提交数据库密码、Cookie、令牌、Provider 密钥或其他真实敏感信息。

## 目录结构

- `apps/server`：FastAPI 服务端、数据库迁移和服务端测试
- `apps/web`：Vue 3 客户端及客户端测试
- `packages/ui`：共享客户端界面组件
- `tests/e2e`：端到端测试

## 许可证

本项目基于 [MIT License](LICENSE) 发布。
