"""Subprocess helpers for the HyperFrames CLI.

Golden rules (from the plan):
- stdin=DEVNULL — `hyperframes tts` drains fd 0 and would eat a piped script.
- capture stdout/stderr separately; returncode is the SOLE authority for success.
  Never pipe through tail (masks exit status → false-green).
- always invoke the pinned CLI via the sidecar's node_modules npx bin.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from dataclasses import dataclass

from ..settings import Settings


@dataclass
class ProcResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class HFError(RuntimeError):
    pass


class SidecarUnavailableError(RuntimeError):
    """Sidecar unreachable/refused at connect time → caller may fall back to the CLI."""


# config quality (UI: draft/looks/delivery) → producer /render vocab (draft/standard/high)
_QUALITY_TO_SIDECAR = {"draft": "draft", "looks": "standard", "standard": "standard",
                       "delivery": "high", "high": "high"}


class HF:
    def __init__(self, settings: Settings) -> None:
        self.s = settings

    def _cmd_prefix(self) -> list[str]:
        """Prefer the installed sidecar binary (no re-download, no network); fall
        back to npx only if it's absent."""
        binp = self.s.sidecar_dir / "node_modules" / ".bin" / "hyperframes"
        if binp.exists():
            return [str(binp)]
        return ["npx", "--yes", f"hyperframes@{self.s.hf_version}"]

    async def run(self, args: list[str], *, cwd: str | None = None, timeout: float = 600) -> ProcResult:
        """Run `hyperframes <args...>` (installed binary or npx)."""
        import os

        cmd = [*self._cmd_prefix(), *args]
        env = {
            **os.environ,
            "HYPERFRAMES_PYTHON": self.s.python_bin(),  # venv with kokoro-onnx
            "PUPPETEER_CACHE_DIR": str(self.s.cache_dir / "browser"),
        }
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd or str(self.s.sidecar_dir),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise HFError(f"hyperframes {' '.join(args)} timed out after {timeout}s")
        return ProcResult(proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"))

    async def tts(self, text_file: str, out_wav: str, *, voice: str, lang: str, speed: float = 1.0) -> dict:
        """Synthesize one line; return the parsed --json payload (durationSeconds etc.)."""
        from .. import narration

        text = Path(text_file).read_text(encoding="utf-8")
        spoken = narration.clean(text)
        eff = max(0.5, min(2.0, round(speed * narration.rate(spoken), 3)))
        if lang == "zh":
            # espeak-ng (what `hyperframes tts` uses) cannot carry Mandarin tones into
            # Kokoro's vocabulary — see monoline/tts_zh.py. Fall back to the CLI only if
            # the tone path is unavailable or fails; a toneless line beats a failed job.
            from .. import tts_zh

            if tts_zh.available():
                try:
                    dur = await asyncio.to_thread(
                        tts_zh.synthesize, spoken, voice, out_wav, speed=eff
                    )
                    return {"durationSeconds": dur, "engine": "kokoro+misaki"}
                except Exception as exc:  # noqa: BLE001
                    import sys

                    print(f"zh tone path failed ({exc}); falling back to hyperframes tts", file=sys.stderr)
        # the fallback engine gets the same cleaned text and the same rate decision
        if spoken != text.strip():
            scrubbed = Path(out_wav).with_suffix(".clean.txt")
            scrubbed.write_text(spoken, encoding="utf-8")
            text_file = str(scrubbed)
        args = ["tts", text_file, "--voice", voice, "--lang", lang, "-o", out_wav, "--json"]
        if eff != 1.0:
            args += ["--speed", str(eff)]
        r = await self.run(args, timeout=300)
        if not r.ok:
            raise HFError(f"tts failed rc={r.returncode}: {r.stderr[-400:]}")
        m = re.search(r"\{.*\}", r.stdout, re.S)
        if not m:
            raise HFError(f"tts returned no JSON: {r.stdout[-200:]}")
        return json.loads(m.group(0))

    async def lint(self, project_dir: str) -> tuple[bool, dict]:
        """Return (ok, data). ok = process succeeded AND no error-severity findings.
        Warnings (e.g. nested_structure_needs_subcomposition) do not block."""
        r = await self.run(["lint", "--json", project_dir], cwd=project_dir, timeout=120)
        data: dict = {}
        m = re.search(r"\{.*\}", r.stdout, re.S)
        if m:
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        findings = data.get("findings") or []
        errors = [f for f in findings if f.get("severity") == "error"]
        data["_error_count"] = len(errors)
        ok = r.ok and len(errors) == 0
        return ok, data

    async def render(self, project_dir: str, out_path: str, *, fps: int = 30, quality: str = "standard",
                     fmt: str = "mp4") -> ProcResult:
        r = await self.run(
            ["render", project_dir, "-o", out_path, "--fps", str(fps), "--quality", quality, "--format", fmt],
            cwd=project_dir,
            timeout=1800,
        )
        if not r.ok:
            raise HFError(f"render failed rc={r.returncode}: {r.stderr[-600:]}")
        return r

    async def render_via_sidecar(self, project_dir: str, out_path: str, *, fps: int = 30,
                                 quality: str = "standard", fmt: str = "mp4", timeout: float = 1800) -> dict:
        """Render through the producer HTTP server (persistent Chrome pool, shared FS).
        Raises SidecarUnavailableError on connect failure (→ CLI fallback), HFError on a
        real render failure (→ no fallback; the composition itself is broken)."""
        import httpx

        q = _QUALITY_TO_SIDECAR.get(quality, "standard")
        payload = {"projectDir": str(project_dir), "output": str(out_path),
                   "fps": fps, "quality": q, "format": fmt}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=5)) as client:
                resp = await client.post(f"{self.s.sidecar_url}/render", json=payload)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise SidecarUnavailableError(str(e)) from e
        except httpx.TimeoutException as e:
            raise HFError(f"sidecar render timed out after {timeout}s") from e
        except httpx.HTTPError as e:  # reset / protocol errors → sidecar unusable
            raise SidecarUnavailableError(str(e)) from e
        # A gateway/unavailable status means the sidecar isn't serving right now → fall back.
        if resp.status_code in (502, 503, 504):
            raise SidecarUnavailableError(f"HTTP {resp.status_code}")
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            if resp.status_code >= 500:
                raise SidecarUnavailableError(f"HTTP {resp.status_code} (non-JSON body)")
            raise HFError(f"sidecar render bad response {resp.status_code}: {resp.text[:300]}")
        # A structured success:false is a REAL render error (CLI would hit the same) → no fallback.
        if resp.status_code >= 500 or not data.get("success"):
            raise HFError(f"sidecar render failed: {data.get('error') or resp.text[:300]}")
        return data
