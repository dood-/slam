SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := run

UV ?= uv
NPM ?= npm
HOST ?= 127.0.0.1
API_PORT ?= 8000
WEB_PORT ?= 4173
DEV_PORT ?= 5173

.PHONY: run dev install build backend frontend help

install: backend/.venv/.slam-installed frontend/node_modules/.slam-installed

backend/.venv/.slam-installed: backend/pyproject.toml backend/uv.lock
	$(UV) sync --project backend --locked
	touch $@

frontend/node_modules/.slam-installed: frontend/package.json frontend/package-lock.json
	$(NPM) --prefix frontend ci
	touch $@

build: install
	$(NPM) --prefix frontend run build

# Each server has its own process group, including npm/Vite children.
# Stop both groups on Ctrl+C or when either server exits.
define serve
	@command -v setsid >/dev/null || { echo 'Для запуска нужен setsid (util-linux).'; exit 1; }; \
	api_pid=''; web_pid=''; \
	cleanup() { \
		trap - EXIT INT TERM; \
		for pid in "$$api_pid" "$$web_pid"; do \
			if [[ -n "$$pid" ]]; then kill -TERM -- "-$$pid" 2>/dev/null || true; fi; \
		done; \
		wait 2>/dev/null || true; \
	}; \
	trap cleanup EXIT; \
	trap 'exit 130' INT; \
	trap 'exit 143' TERM; \
	echo 'Приложение: http://$(HOST):$(1) · API: http://$(HOST):$(API_PORT)/docs'; \
	setsid $(UV) run --project backend --no-sync uvicorn slam.api:app --host '$(HOST)' --port '$(API_PORT)' & api_pid=$$!; \
	SLAM_API_URL='http://$(HOST):$(API_PORT)' setsid $(NPM) --prefix frontend run $(2) -- --host '$(HOST)' --port '$(1)' --strictPort & web_pid=$$!; \
	wait -n "$$api_pid" "$$web_pid"
endef

run: build
	$(call serve,$(WEB_PORT),preview)

dev: install
	$(call serve,$(DEV_PORT),dev)

backend: backend/.venv/.slam-installed
	$(UV) run --project backend --no-sync uvicorn slam.api:app --host '$(HOST)' --port '$(API_PORT)'

frontend: build
	SLAM_API_URL='http://$(HOST):$(API_PORT)' $(NPM) --prefix frontend run preview -- --host '$(HOST)' --port '$(WEB_PORT)' --strictPort

help:
	@echo 'make          Установить зависимости, собрать и запустить приложение'
	@echo 'make dev      Запустить API и frontend с обновлением при изменении файлов Vue'
	@echo 'make install  Установить зависимости из lock-файлов'
	@echo 'make build    Собрать frontend'
	@echo 'make backend  Запустить только API'
	@echo 'make frontend Запустить только собранный frontend'
	@echo 'Порты: make run API_PORT=8001 WEB_PORT=4174'
