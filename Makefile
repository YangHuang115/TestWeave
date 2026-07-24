SHELL := /bin/sh
.DEFAULT_GOAL := help

UV_CACHE_DIR ?= $(CURDIR)/.cache/uv
UV_NATIVE_TLS ?= true
NPM_CONFIG_CACHE ?= $(CURDIR)/.cache/npm

POSTGRES_PORT ?= 5432
SERVER_PORT ?= 8000
WEB_PORT ?= 5173

.PHONY: help setup doctor db-up db-down reset-db migrate server gateway ai-runtime-worker web test-server test-server-integration test-e2e check-server check-web check clean

help:
	@echo "make setup                     安装并锁定前后端依赖"
	@echo "make doctor                    体检本地环境（docker/uv/node/端口/数据库）"
	@echo "make db-up                     启动 PostgreSQL"
	@echo "make db-down                   停止并移除容器"
	@echo "make reset-db                  重置本地开发数据库（销毁数据卷后重建并迁移）"
	@echo "make migrate                   升级数据库到最新迁移"
	@echo "make server                    启动 FastAPI 开发服务"
	@echo "make gateway                   启动 Agent 网关"
	@echo "make ai-runtime-worker         启动 AI Runtime 工作进程"
	@echo "make web                       启动 Vue 开发服务"
	@echo "make test-server               运行后端单元测试"
	@echo "make test-server-integration   运行后端集成测试（临时 PostgreSQL）"
	@echo "make test-e2e                  运行端到端测试"
	@echo "make check-server              运行后端门禁（lint/format/mypy/测试）"
	@echo "make check-web                 运行前端门禁（format/lint/测试/构建）"
	@echo "make check                     运行 P0 全部门禁"
	@echo "make clean                     清理构建产物与本地缓存"
	@echo "make help                      显示本帮助"

setup:
	UV_CACHE_DIR=$(UV_CACHE_DIR) UV_NATIVE_TLS=$(UV_NATIVE_TLS) uv sync --project apps/server --frozen
	NPM_CONFIG_CACHE=$(NPM_CONFIG_CACHE) npm ci

doctor:
	@set -u; \
		fail=0; \
		port_in_use() { \
			if command -v lsof >/dev/null 2>&1; then lsof -nP -iTCP:"$$1" -sTCP:LISTEN >/dev/null 2>&1; return $$?; \
			elif command -v nc >/dev/null 2>&1; then nc -z 127.0.0.1 "$$1" >/dev/null 2>&1; return $$?; \
			else return 2; fi; \
		}; \
		echo "== TestWeave doctor =="; \
		printf '检查 docker ... '; \
		if command -v docker >/dev/null 2>&1; then \
			if docker compose version >/dev/null 2>&1; then echo "OK ($$(docker --version 2>/dev/null))"; \
			else echo "FAIL: 未找到 docker compose 插件"; fail=1; fi; \
		else echo "FAIL: 未安装 docker"; fail=1; fi; \
		printf '检查 uv ... '; \
		if command -v uv >/dev/null 2>&1; then echo "OK ($$(uv --version 2>/dev/null))"; \
		else echo "FAIL: 未安装 uv"; fail=1; fi; \
		printf '检查 node ... '; \
		if command -v node >/dev/null 2>&1; then echo "OK ($$(node --version 2>/dev/null))"; \
		else echo "FAIL: 未安装 node"; fail=1; fi; \
		printf '检查 npm ... '; \
		if command -v npm >/dev/null 2>&1; then echo "OK ($$(npm --version 2>/dev/null))"; \
		else echo "FAIL: 未安装 npm"; fail=1; fi; \
		for spec in "server:$(SERVER_PORT)" "web:$(WEB_PORT)"; do \
			name=$${spec%%:*}; p=$${spec##*:}; \
			printf '检查端口 %s (%s) ... ' "$$p" "$$name"; \
			port_in_use "$$p"; rc=$$?; \
			if [ "$$rc" -eq 0 ]; then echo "FAIL: 端口被占用，开发服务可能无法启动"; fail=1; \
			elif [ "$$rc" -eq 2 ]; then echo "SKIP: 缺少 lsof/nc，无法检测"; \
			else echo "OK: 空闲"; fi; \
		done; \
		printf '检查数据库可用性 ... '; \
		if command -v docker >/dev/null 2>&1 && docker compose exec -T postgres pg_isready -U "$${POSTGRES_USER:-testweave}" -d "$${POSTGRES_DB:-testweave}" >/dev/null 2>&1; then \
			echo "OK: pg_isready 通过"; \
		elif port_in_use "$(POSTGRES_PORT)"; then \
			echo "OK: 端口 $(POSTGRES_PORT) 有监听"; \
		else \
			echo "FAIL: 数据库不可达，请先 make db-up"; fail=1; \
		fi; \
		if [ "$$fail" -ne 0 ]; then echo "doctor: 发现问题，请按上面 FAIL 项处理"; exit 1; \
		else echo "doctor: 所有检查通过"; fi

db-up:
	docker compose up -d --wait postgres

db-down:
	docker compose down

reset-db:
	docker compose down --volumes
	$(MAKE) db-up
	$(MAKE) migrate

migrate:
	UV_CACHE_DIR=$(UV_CACHE_DIR) UV_NATIVE_TLS=$(UV_NATIVE_TLS) uv run --project apps/server alembic -c apps/server/alembic.ini upgrade head

server:
	UV_CACHE_DIR=$(UV_CACHE_DIR) UV_NATIVE_TLS=$(UV_NATIVE_TLS) uv run --project apps/server uvicorn testweave.main:app --app-dir apps/server/src --host 127.0.0.1 --port 8000 --reload

gateway:
	UV_CACHE_DIR=$(UV_CACHE_DIR) UV_NATIVE_TLS=$(UV_NATIVE_TLS) uv run --project apps/server python3 -m testweave.cli start-gateway

ai-runtime-worker:
	UV_CACHE_DIR=$(UV_CACHE_DIR) UV_NATIVE_TLS=$(UV_NATIVE_TLS) TESTWEAVE_AI_RUNTIME__ENABLED=true uv run --project apps/server python3 -m testweave.cli runtime-worker --forever

web:
	NPM_CONFIG_CACHE=$(NPM_CONFIG_CACHE) npm run dev:web

test-server:
	cd apps/server && UV_CACHE_DIR=$(UV_CACHE_DIR) UV_NATIVE_TLS=$(UV_NATIVE_TLS) uv run pytest -m "not integration"

test-server-integration:
	@set -e; \
		POSTGRES_PASSWORD=integration-profile-not-used docker compose -p testweave-integration --profile test up -d --wait postgres-test; \
		trap 'POSTGRES_PASSWORD=integration-profile-not-used docker compose -p testweave-integration --profile test down --volumes --remove-orphans >/dev/null' EXIT INT TERM; \
		cd apps/server; \
		TESTWEAVE_ENVIRONMENT=test \
		TESTWEAVE_TEST_DATABASE_URL=postgresql+psycopg://testweave:local-integration-test-only@127.0.0.1:55432/testweave_test \
		UV_CACHE_DIR=$(UV_CACHE_DIR) UV_NATIVE_TLS=$(UV_NATIVE_TLS) uv run pytest -m integration

check-server:
	cd apps/server && UV_CACHE_DIR=$(UV_CACHE_DIR) UV_NATIVE_TLS=$(UV_NATIVE_TLS) uv run ruff check .
	cd apps/server && UV_CACHE_DIR=$(UV_CACHE_DIR) UV_NATIVE_TLS=$(UV_NATIVE_TLS) uv run ruff format --check .
	cd apps/server && UV_CACHE_DIR=$(UV_CACHE_DIR) UV_NATIVE_TLS=$(UV_NATIVE_TLS) uv run mypy
	$(MAKE) test-server

check-web:
	NPM_CONFIG_CACHE=$(NPM_CONFIG_CACHE) npm run format:check
	NPM_CONFIG_CACHE=$(NPM_CONFIG_CACHE) npm run lint:web
	NPM_CONFIG_CACHE=$(NPM_CONFIG_CACHE) npm run test:web
	NPM_CONFIG_CACHE=$(NPM_CONFIG_CACHE) npm run build:web

check: check-server check-web

test-e2e:
	npx playwright test -c tests/e2e/playwright.config.ts

clean:
	rm -rf .cache .ruff_cache .mypy_cache .pytest_cache
	rm -rf apps/server/.ruff_cache apps/server/.mypy_cache apps/server/.pytest_cache
	rm -rf apps/web/dist test-results
	find apps/server/src tools -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
