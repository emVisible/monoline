"""Runtime settings & path resolution for Monoline.

Single source of truth for: where user data lives, which ports we bind, which
node/python binaries we exec, and where the built SPA is served from.

Everything is overridable via MONOLINE_* env vars so a container or a second
install can relocate state without code changes.
"""
from __future__ import annotations

import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


class Settings:
    # --- app data (NEVER inside the repo; survives re-clones) -----------------
    app_dir: Path = Path(
        _env("MONOLINE_APP_DIR", str(Path.home() / "Library" / "Application Support" / "Monoline"))
    )

    # --- network (localhost only; single port the user knows) -----------------
    host: str = _env("MONOLINE_HOST", "127.0.0.1")
    port: int = int(_env("MONOLINE_PORT", "8787"))
    sidecar_port: int = int(_env("MONOLINE_SIDECAR_PORT", "8790"))

    # --- repo layout (this file is backend/src/monoline/settings.py) ----------
    # parents: [0]=monoline [1]=src [2]=backend [3]=<repo root>
    backend_dir: Path = Path(__file__).resolve().parents[2]
    repo_root: Path = Path(__file__).resolve().parents[3]
    design_tokens_dir: Path = repo_root / "design" / "tokens"
    vendor_dir: Path = backend_dir / "vendor"
    static_dir: Path = Path(_env("MONOLINE_STATIC_DIR", str(Path(__file__).resolve().parent / "static")))

    # --- hyperframes pin (CLI + producer + player share one line) -------------
    hf_version: str = _env("MONOLINE_HF_VERSION", "0.8.63")

    # --- render path: producer sidecar (persistent Chrome pool) is primary; ----
    # --- set MONOLINE_RENDER_VIA_SIDECAR=0 to force the CLI subprocess. ---------
    render_via_sidecar: bool = _env("MONOLINE_RENDER_VIA_SIDECAR", "1") == "1"

    # --- LLM script-writing (V1): OpenAI-compatible; point base_url at a local ---
    # --- Ollama/LM Studio for fully-offline. Unconfigured → the feature is off. --
    llm_base_url: str = _env("MONOLINE_LLM_BASE_URL", "https://api.openai.com/v1")
    llm_api_key: str = _env("MONOLINE_LLM_API_KEY", "")
    llm_model: str = _env("MONOLINE_LLM_MODEL", "gpt-4o-mini")
    # --- a small local model degrades on long prompts (and can OOM the host), so the ----
    # --- storyboard upgrade walks the weak beats in batches under both budgets. ---------
    llm_batch_beats: int = int(_env("MONOLINE_LLM_BATCH_BEATS", "3"))
    llm_batch_chars: int = int(_env("MONOLINE_LLM_BATCH_CHARS", "900"))
    # --- and the whole storyboard pass gets a wall-clock ceiling: a local model at ~1 char/s ----
    # --- otherwise costs 240s per timed-out batch inside the `plan` stage. ----------------------
    llm_plan_seconds: int = int(_env("MONOLINE_LLM_PLAN_SECONDS", "150"))

    @property
    def llm_ready(self) -> bool:
        # Ollama/local servers accept a dummy key; treat any base_url + non-empty
        # key (or a localhost base_url) as "configured".
        return bool(self.llm_api_key) or "localhost" in self.llm_base_url or "127.0.0.1" in self.llm_base_url

    @property
    def db_path(self) -> Path:
        return self.app_dir / "app.db"

    @property
    def workspaces_dir(self) -> Path:
        return self.app_dir / "workspaces"

    @property
    def cache_dir(self) -> Path:
        return self.app_dir / "cache"

    @property
    def logs_dir(self) -> Path:
        return self.app_dir / "logs"

    @property
    def sidecar_dir(self) -> Path:
        return self.repo_root / "sidecar"

    @property
    def sidecar_url(self) -> str:
        return f"http://127.0.0.1:{self.sidecar_port}"

    def ensure_dirs(self) -> None:
        for p in (self.app_dir, self.workspaces_dir, self.cache_dir, self.logs_dir):
            p.mkdir(parents=True, exist_ok=True)

    # --- binary resolution ----------------------------------------------------
    def resolve_node(self) -> str | None:
        """Prefer an explicit node, then nvm 22, then PATH — but never a node
        outside [22,23) for the sidecar (Vite/HF pin). Returns abs path or None."""
        explicit = _env("MONOLINE_NODE_BIN", "")
        if explicit and Path(explicit).exists():
            return explicit
        candidates = [
            Path.home() / ".nvm" / "versions" / "node" / "v22.14.0" / "bin" / "node",
            Path(shutil.which("node") or ""),
        ]
        for c in candidates:
            if c and c.exists():
                return str(c)
        return None

    def python_bin(self) -> str:
        """The venv python that ALSO serves as HYPERFRAMES_PYTHON (has kokoro-onnx).
        Under `uv run`, sys.executable is already the pinned 3.11 venv python."""
        return _env("MONOLINE_PYTHON", sys.executable)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
