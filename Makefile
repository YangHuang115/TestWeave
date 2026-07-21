SHELL := /bin/sh
.DEFAULT_GOAL := help

UV_CACHE_DIR ?= $(CURDIR)/.cache/uv
UV_NATIVE_TLS ?= true
NPM_CONFIG_CACHE ?= $(CURDIR)/.cache/npm

.PHONY: help setup db-up db-down migrate server web test-server test-server-integration check-server check-web check

help:
	@echo "make setup                    安装并锁定前后端依赖"
	@echo "make db-up                    启动 PostgreSQL"
	@echo "make migrate                  升级数据库到最新迁移"
	@echo "make server                   启动 FastAPI 开发服务"
	@echo "make web                      启动 Vue 开发服务"
	@echo "make check                    运行 P0 全部门禁"

setup:
	UV_CACHE_DIR=$(UV_CACHE_DIR) UV_NATIVE_TLS=$(UV_NATIVE_TLS) uv sync --project apps/server --frozen
	NPM_CONFIG_CACHE=$(NPM_CONFIG_CACHE) npm ci

db-up:
	docker compose up -d --wait postgres

db-down:
	docker compose down

migrate:
	UV_CACHE_DIR=$(UV_CACHE_DIR) UV_NATIVE_TLS=$(UV_NATIVE_TLS) uv run --project apps/server alembic -c apps/server/alembic.ini upgrade head

server:
	UV_CACHE_DIR=$(UV_CACHE_DIR) UV_NATIVE_TLS=$(UV_NATIVE_TLS) uv run --project apps/server uvicorn testweave.main:app --app-dir apps/server/src --host 127.0.0.1 --port 8000 --reload

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
