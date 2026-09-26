"""Job manager — owns the Repo connection and runs pipelines as background tasks.

Single-user, concurrency=1: one asyncio.Queue + one worker. Durability is the DB
(stage rows), so a crash mid-job resumes on restart (M3 wires reconcile fully;
M1 just re-runs on demand). SSE fan-out is M3; the M1 frontend polls hydration.
"""
from __future__ import annotations

import asyncio

from ..db.repo import Repo
from ..pipeline.runner import JobCancelled, run_pipeline
from ..settings import Settings


class JobManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.repo = Repo(settings.db_path)
        self._queue: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._cancel: dict[str, asyncio.Event] = {}
        self._subs: dict[str, set[asyncio.Queue]] = {}

    # --- SSE fan-out: live stage events pushed to any open /stream listeners ----
    def subscribe(self, jid: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subs.setdefault(jid, set()).add(q)
        return q

    def unsubscribe(self, jid: str, q: asyncio.Queue) -> None:
        subs = self._subs.get(jid)
        if subs:
            subs.discard(q)
            if not subs:
                self._subs.pop(jid, None)

    async def publish(self, jid: str, payload: dict) -> None:
        for q in list(self._subs.get(jid, ())):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass  # slow consumer; drop (client refetches on reconnect)

    async def start(self) -> None:
        await self.repo.connect()
        await self.reconcile()
        self._worker = asyncio.create_task(self._loop())

    async def reconcile(self) -> list[str]:
        """Re-enqueue jobs orphaned by an unclean shutdown. The queue is in-memory,
        so a job left ``running``/``queued`` in the DB has no live worker — resume it
        (P0 stage caching means completed stages are skipped). Returns the resumed ids.
        A job whose pipeline genuinely fails flips to ``failed`` and won't re-reconcile.
        """
        stuck = await self.repo.list_by_status(("running", "queued"))
        for j in stuck:
            await self.repo.update_job(j["id"], status="queued")
            await self.repo.add_event(j["id"], "reconcile", level="warn",
                                       message="服务重启，自动续跑中断的作业")
            await self.enqueue(j["id"], force=False)
        return [j["id"] for j in stuck]

    async def stop(self) -> None:
        for ev in self._cancel.values():
            ev.set()
        if self._worker:
            self._worker.cancel()

    async def create_job(self, *, script: str, config: dict, canvas: dict, start: bool = True) -> str:
        """Persist a job; `start=False` leaves it queued-out so the caller can finish
        wiring it (e.g. freeze the brand logo into its assets) before it runs."""
        jid = await self.repo.create_job(
            script_text=script, config=config, canvas=canvas, title="", slug="")
        if start:
            await self.enqueue(jid)
        return jid

    async def enqueue(self, jid: str, *, force: bool = False) -> None:
        self._cancel.setdefault(jid, asyncio.Event())
        # The worker is serial, so a request can wait here for minutes behind a long film.
        # Mark it now: an in-memory queue is invisible, and a job still reading `draft` while
        # it waits is what "点了 Render 没反应" looked like (measured: 18 min of nothing, then
        # it started by itself the second the previous render finished).
        job = await self.repo.get_job(jid)
        if job and job["status"] not in ("running", "queued"):
            await self.repo.update_job(jid, status="queued")
        await self._queue.put((jid, force))

    def cancel(self, jid: str) -> bool:
        if jid in self._cancel and not self._cancel[jid].is_set():
            self._cancel[jid].set()
            return True
        return False

    async def _loop(self) -> None:
        while True:
            jid, force = await self._queue.get()
            ev = self._cancel.setdefault(jid, asyncio.Event())
            ev.clear()

            async def progress(stage: str, data: dict, _jid: str = jid) -> None:
                await self.publish(_jid, {"type": "stage", **data})

            try:
                await run_pipeline(self.repo, self.settings, jid, force=force, cancel=ev, progress=progress)
            except JobCancelled:
                pass
            except Exception:  # noqa: BLE001 — runner already persisted failure to DB
                pass
            finally:
                job = await self.repo.get_job(jid)
                await self.publish(jid, {"type": "done", "status": (job or {}).get("status", "failed")})
                self._cancel.pop(jid, None)
                self._queue.task_done()
