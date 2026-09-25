# Monoline — local text→video tool. Single documented command surface.
# Requires: uv (Python 3.11), corepack/pnpm (Node 22 via .nvmrc), ffmpeg on PATH.

.DEFAULT_GOAL := help
NODE22 := $(HOME)/.nvm/versions/node/v22.14.0/bin

.PHONY: help bootstrap backend web sidecar start serve dev doctor test warmup fonts clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "};{printf "  \033[36m%-12s\033[0m %s\n",$$1,$$2}'

bootstrap: ## One-shot: uv sync (py3.11) + pnpm install (web+sidecar) + producer resolve check
	uv python install 3.11
	uv sync --directory backend
	corepack enable || true
	pnpm install
	@echo "→ verifying @hyperframes/producer resolves in sidecar..."
	cd sidecar && node -e "require.resolve('@hyperframes/producer/server')" && echo "  producer OK"
	@echo "→ hyperframes doctor..."
	cd sidecar && node -e "const {execFileSync}=require('child_process'); const o=execFileSync('./node_modules/.bin/hyperframes',['doctor','--json'],{encoding:'utf8'}); const j=JSON.parse(o.slice(o.indexOf('{'))); process.exit(j.ok?0:1)" || echo "  ⚠ doctor reported problems — run 'make doctor' and check /setup"
	@echo "✓ bootstrap complete. Run 'make start'."

backend: ## uv sync the backend only
	uv sync --directory backend

web: ## install/build the frontend only
	pnpm --filter @monoline/web build

sidecar: ## install the render sidecar deps
	pnpm --filter @monoline/sidecar install

serve: ## Run the backend API (dev, reload)
	uv run --directory backend monoline serve --reload

start: ## Build-if-missing, spawn sidecar, open browser (single command)
	uv run --directory backend monoline start

dev: ## Backend + Vite dev server (two processes; open http://localhost:5173)
	@echo "terminal 1: make serve   |  terminal 2: pnpm --filter @monoline/web dev"
	@echo "then open http://localhost:5173 (proxies /api,/w,/events → :8787)"

doctor: ## Show resolved environment truth (node/ffmpeg/chrome/fonts/sidecar)
	uv run --directory backend monoline doctor

test: ## The whole suite: backend pytest + SPA typecheck (run this, not an ad-hoc pytest)
	@uv run --directory backend pytest tests/ -q
	@# tests/test_i18n_coverage.py reads web/src/*.tsx as text, so a syntactically broken
	@# SPA can pass the Python suite. tsc is the only thing that proves it compiles.
	@cd web && pnpm exec tsc --noEmit

warmup: ## Render a 2s synthetic fixture end-to-end to prove the toolchain
	uv run --directory backend monoline warmup

fonts: ## Verify the vendored OFL CJK font + subset pipeline
	uv run --directory backend monoline fonts --verify

clean: ## Remove build artifacts (never touches user workspaces)
	rm -rf web/dist backend/src/monoline/static/* sidecar/node_modules
