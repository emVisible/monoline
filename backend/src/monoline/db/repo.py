"""Thin async SQLite repository (no ORM). Schema stays visible; ~1 file.

Single-writer model: the M1 asyncio worker is concurrency=1, so contention is
nil; WAL + busy_timeout cover the read-only API handlers.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

import aiosqlite

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def new_id() -> str:
    # sortable-ish: timestamp prefix + random (good enough for a local tool)
    return f"{int(time.time()*1000):013x}{uuid.uuid4().hex[:10]}"


class Repo:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._migrate()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._conn, "call connect() first"
        return self._conn

    async def _migrate(self) -> None:
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT)"
        )
        cur = await self.db.execute("SELECT version FROM schema_version")
        applied = {r[0] for r in await cur.fetchall()}
        for f in sorted(_MIGRATIONS_DIR.glob("*.sql")):
            ver = int(f.name.split("_", 1)[0])
            if ver in applied:
                continue
            sql = f.read_text()
            await self.db.executescript(sql)
            await self.db.execute(
                "INSERT INTO schema_version(version, applied_at) VALUES(?,?)", (ver, now_iso())
            )
        await self.db.commit()

    # --- jobs -----------------------------------------------------------------
    async def create_job(self, *, script_text: str, config: dict, canvas: dict, title: str, slug: str) -> str:
        jid = new_id()
        t = now_iso()
        await self.db.execute(
            """INSERT INTO jobs(id, slug, title, status, script_text, config_json, canvas_json, created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (jid, slug, title, "draft", script_text, json.dumps(config), json.dumps(canvas), t, t),
        )
        await self.db.commit()
        return jid

    async def get_job(self, jid: str) -> dict | None:
        cur = await self.db.execute("SELECT * FROM jobs WHERE id=?", (jid,))
        r = await cur.fetchone()
        return dict(r) if r else None

    async def update_job(self, jid: str, **fields: Any) -> None:
        fields = {k: (json.dumps(v) if k.endswith("_json") and not isinstance(v, str) else v) for k, v in fields.items()}
        fields["updated_at"] = now_iso()
        cols = ", ".join(f"{k}=?" for k in fields)
        await self.db.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), jid))
        await self.db.commit()

    async def list_jobs(self, *, limit: int = 50) -> list[dict]:
        cur = await self.db.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in await cur.fetchall()]

    async def list_by_status(self, statuses: tuple[str, ...]) -> list[dict]:
        qs = ",".join("?" for _ in statuses)
        cur = await self.db.execute(
            f"SELECT * FROM jobs WHERE status IN ({qs}) ORDER BY created_at", statuses
        )
        return [dict(r) for r in await cur.fetchall()]

    # --- stages ---------------------------------------------------------------
    async def upsert_stage(self, jid: str, key: str, seq: int, **fields: Any) -> None:
        await self.db.execute(
            "INSERT OR IGNORE INTO job_stages(job_id, key, seq, status) VALUES(?,?,?,'pending')",
            (jid, key, seq),
        )
        if fields:
            cols = ", ".join(f"{k}=?" for k in fields)
            await self.db.execute(f"UPDATE job_stages SET {cols} WHERE job_id=? AND key=?", (*fields.values(), jid, key))
        await self.db.commit()

    async def get_stages(self, jid: str) -> list[dict]:
        cur = await self.db.execute("SELECT * FROM job_stages WHERE job_id=? ORDER BY seq", (jid,))
        return [dict(r) for r in await cur.fetchall()]

    async def get_stage(self, jid: str, key: str) -> dict | None:
        cur = await self.db.execute("SELECT * FROM job_stages WHERE job_id=? AND key=?", (jid, key))
        r = await cur.fetchone()
        return dict(r) if r else None

    # --- segments -------------------------------------------------------------
    async def replace_segments(self, jid: str, rows: list[dict]) -> None:
        await self.db.execute("DELETE FROM segments WHERE job_id=?", (jid,))
        for r in rows:
            await self.db.execute(
                """INSERT INTO segments(job_id,i,text,line_no,wav_path,wav_bytes,tts_duration,start,end,audio_source,voice,lang,speed)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (jid, r["i"], r["text"], r.get("line_no"), r.get("wav_path"), r.get("wav_bytes"),
                 r.get("tts_duration"), r.get("start"), r.get("end"), r.get("audio_source", "tts"),
                 r.get("voice"), r.get("lang"), r.get("speed")),
            )
        await self.db.commit()

    async def get_segments(self, jid: str) -> list[dict]:
        cur = await self.db.execute("SELECT * FROM segments WHERE job_id=? ORDER BY i", (jid,))
        return [dict(r) for r in await cur.fetchall()]

    # --- plans ----------------------------------------------------------------
    async def save_plan(self, jid: str, plan_json: str, source: str, warnings: list[str]) -> int:
        cur = await self.db.execute("SELECT COALESCE(MAX(version),0) FROM scene_plans WHERE job_id=?", (jid,))
        ver = (await cur.fetchone())[0] + 1
        await self.db.execute(
            "INSERT INTO scene_plans(job_id,version,plan_json,source,warnings_json,created_at) VALUES(?,?,?,?,?,?)",
            (jid, ver, plan_json, source, json.dumps(warnings), now_iso()),
        )
        await self.db.commit()
        return ver

    async def get_plan(self, jid: str) -> dict | None:
        cur = await self.db.execute(
            "SELECT * FROM scene_plans WHERE job_id=? ORDER BY version DESC LIMIT 1", (jid,)
        )
        r = await cur.fetchone()
        return dict(r) if r else None

    # --- artifacts ------------------------------------------------------------
    async def add_artifact(self, jid: str, **f: Any) -> str:
        aid = new_id()
        await self.db.execute(
            """INSERT INTO artifacts(id,job_id,stage_key,kind,rel_path,abs_path,mime,size_bytes,sha256,
               duration_seconds,fps,width,height,state,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (aid, jid, f.get("stage_key"), f["kind"], f.get("rel_path"), f.get("abs_path"), f.get("mime"),
             f.get("size_bytes"), f.get("sha256"), f.get("duration_seconds"), f.get("fps"), f.get("width"),
             f.get("height"), f.get("state", "local"), now_iso()),
        )
        await self.db.commit()
        return aid

    async def get_artifacts(self, jid: str) -> list[dict]:
        cur = await self.db.execute("SELECT * FROM artifacts WHERE job_id=? ORDER BY created_at", (jid,))
        return [dict(r) for r in await cur.fetchall()]

    # --- events ---------------------------------------------------------------
    async def add_event(self, jid: str, kind: str, *, stage_key: str | None = None, level: str = "info",
                        message: str | None = None, data: dict | None = None) -> int:
        cur = await self.db.execute(
            "INSERT INTO events(job_id,ts,kind,stage_key,level,message,data_json) VALUES(?,?,?,?,?,?,?)",
            (jid, now_iso(), kind, stage_key, level, message, json.dumps(data) if data else None),
        )
        await self.db.commit()
        return cur.lastrowid

    async def get_events_since(self, jid: str, after_id: int = 0) -> list[dict]:
        cur = await self.db.execute(
            "SELECT * FROM events WHERE job_id=? AND id>? ORDER BY id", (jid, after_id)
        )
        return [dict(r) for r in await cur.fetchall()]

    # --- presets (V2: saved config recipes) -----------------------------------
    async def list_presets(self) -> list[dict]:
        cur = await self.db.execute("SELECT * FROM presets ORDER BY created_at DESC")
        return [{"id": r["id"], "name": r["name"], "config": json.loads(r["config_json"])}
                for r in await cur.fetchall()]

    async def save_preset(self, name: str, config: dict) -> str:
        pid = new_id()
        await self.db.execute(
            "INSERT INTO presets(id,name,config_json,created_at) VALUES(?,?,?,?)",
            (pid, name, json.dumps(config, ensure_ascii=False), now_iso()),
        )
        await self.db.commit()
        return pid

    async def delete_preset(self, pid: str) -> None:
        await self.db.execute("DELETE FROM presets WHERE id=?", (pid,))
        await self.db.commit()
