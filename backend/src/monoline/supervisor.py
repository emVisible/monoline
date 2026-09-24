"""Sidecar lifecycle: Python owns the Node render sidecar process.

The sidecar is stateless (HF's job store is in-memory + TTL), so it may crash
and be restarted without losing a job — durability lives in the Python DB.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx

from .settings import Settings


class SidecarSupervisor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.proc: asyncio.subprocess.Process | None = None
        self.token = os.environ.get("MONOLINE_SIDECAR_TOKEN") or os.urandom(16).hex()

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def start(self) -> bool:
        if self.running:
            return True
        node = self.settings.resolve_node()
        if not node:
            raise RuntimeError("no node 22 resolved — see doctor")
        server = self.settings.sidecar_dir / "server.mjs"
        if not server.exists():
            raise RuntimeError(f"sidecar entry missing: {server}")
        env = {
            **os.environ,
            "SIDECAR_PORT": str(self.settings.sidecar_port),
            "SIDECAR_TOKEN": self.token,
            "PUPPETEER_CACHE_DIR": str(self.settings.cache_dir / "browser"),
            "HYPERFRAMES_RENDERS_DIR": str(self.settings.workspaces_dir),
        }
        self.proc = await asyncio.create_subprocess_exec(
            node, str(server), "--port", str(self.settings.sidecar_port),
            cwd=str(self.settings.sidecar_dir), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        await self._pump_logs()
        return await self.wait_healthy(timeout=20)

    async def _pump_logs(self) -> None:
        assert self.proc and self.proc.stdout
        logf = (self.settings.logs_dir / "sidecar.log").open("ab", buffering=0)
        async def _pump() -> None:
            assert self.proc and self.proc.stdout
            async for line in self.proc.stdout:
                logf.write(line)
        asyncio.create_task(_pump())

    async def wait_healthy(self, timeout: float = 20) -> bool:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                r = await httpx.AsyncClient().get(f"{self.settings.sidecar_url}/health", timeout=1.5)
                if r.status_code == 200:
                    return True
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(0.3)
        return False

    async def stop(self) -> None:
        if self.proc and self.proc.returncode is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), 15)  # SIGTERM the group
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.proc.kill()
        self.proc = None
