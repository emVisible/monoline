"""Monoline CLI (typer). The whole product is reachable from here.

  monoline serve    run the API (dev; optional --reload)
  monoline start    build-if-missing → spawn sidecar → open browser → serve
  monoline doctor   print resolved environment truth
  monoline warmup   render a tiny fixture end-to-end to prove the toolchain
  monoline fonts    (M1+) verify/download the OFL CJK subset source
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import webbrowser
from pathlib import Path

import typer
import uvicorn

from .doctor import run_doctor
from .settings import get_settings
from .supervisor import SidecarSupervisor
from .voices import DEFAULT_VOICE

app = typer.Typer(add_completion=False, help="Monoline — paste a script, get a film.")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="bind host (localhost only)"),
    port: int = typer.Option(0, help="0 = use settings port"),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    settings = get_settings()
    uvicorn.run("monoline.api.app:app", host=host, port=port or settings.port, reload=reload)


@app.command()
def start(
    port: int = typer.Option(0, help="0 = use settings port"),
    open_browser: bool = typer.Option(True, "--open/--no-open"),
) -> None:
    """Build-if-missing, spawn the sidecar, open the browser, serve the API."""
    settings = get_settings()
    port = port or settings.port
    _ensure_frontend_built(settings)

    async def _main() -> None:
        sup = SidecarSupervisor(settings)
        try:
            up = await sup.start()
            typer.echo(f"sidecar: {'ready' if up else 'NOT ready (render disabled)'} @ {settings.sidecar_url}")
        except Exception as e:  # noqa: BLE001
            typer.echo(f"⚠ sidecar failed to start: {e} — the API still serves; render needs the sidecar")
        url = f"http://127.0.0.1:{port}"
        if open_browser:
            webbrowser.open(url)
        typer.echo(f"Monoline → {url}")
        try:
            await uvicorn.Server(uvicorn.Config("monoline.api.app:app", host="127.0.0.1", port=port)).serve()
        finally:
            await sup.stop()

    asyncio.run(_main())


@app.command()
def doctor() -> None:
    """Print resolved environment truth (JSON)."""
    typer.echo(json.dumps(run_doctor(probe_sidecar=False), indent=2, ensure_ascii=False))


@app.command("run-script")
def run_script(
    script: Path = typer.Argument(..., exists=True, help="path to a text script (one line = one beat)"),
    voice: str = typer.Option(DEFAULT_VOICE),
    lang: str = typer.Option("zh"),
    speed: float = typer.Option(1.0),
    quality: str = typer.Option("standard"),
) -> None:
    """Run the full pipeline on a script file and print the resulting MP4 path."""
    import asyncio

    from .db.repo import Repo
    from .pipeline.runner import run_pipeline

    settings = get_settings()
    text = script.read_text(encoding="utf-8")

    async def _go() -> None:
        repo = Repo(settings.db_path)
        await repo.connect()
        try:
            jid = await repo.create_job(
                script_text=text, config={"voice": voice, "lang": lang, "speed": speed, "quality": quality},
                canvas={"width": 1920, "height": 1080, "fps": 30}, title="", slug="")

            async def _prog(stage, d):
                typer.echo(f"  · {stage}: {d.get('status')}" + (f" beat {d.get('beat')}/{d.get('of')}" if d.get('beat') is not None else ""))

            await run_pipeline(repo, settings, jid, progress=_prog)
            arts = await repo.get_artifacts(jid)
            mp4 = next((a["abs_path"] for a in arts if a["kind"] == "render_mp4"), None)
            typer.echo(f"\n✓ job {jid} → {mp4}")
        finally:
            await repo.close()

    asyncio.run(_go())


@app.command()
def warmup(
    quality: str = typer.Option("draft", help="render quality (draft is fastest)"),
    keep: bool = typer.Option(False, "--keep", help="keep the warmup job + workspace instead of cleaning up"),
) -> None:
    """Render a tiny built-in fixture end-to-end to prove the whole toolchain works.

    This is the cold-start acceptance test: uv sync + pnpm install done? ffmpeg +
    Chrome present? sidecar or CLI render reachable? A green run means a pasted
    script will become a real MP4. Uses the CLI render fallback if the sidecar
    isn't running, so it needs no server up first.
    """
    import shutil
    import time

    from .db.repo import Repo
    from .pipeline.runner import run_pipeline

    settings = get_settings()
    fixture = "工具链自检第一拍。\n这是第二拍，收尾。"

    async def _go() -> None:
        repo = Repo(settings.db_path)
        await repo.connect()
        jid: str | None = None
        try:
            jid = await repo.create_job(
                script_text=fixture,
                # llm_plan off: the self-check proves OUR toolchain, and must not pay
                # (or depend on) an optional model server that may be slow or absent.
                config={"quality": quality, "voice": DEFAULT_VOICE, "lang": "zh", "speed": 1.0,
                        "llm_plan": False},
                canvas={"width": 1920, "height": 1080, "fps": 24}, title="", slug="")
            t0 = time.time()

            async def _prog(stage, d):
                typer.echo(f"  · {stage}: {d.get('status')}")

            await run_pipeline(repo, settings, jid, progress=_prog)
            job = await repo.get_job(jid)
            arts = await repo.get_artifacts(jid)
            mp4 = next((a for a in arts if a["kind"] == "render_mp4"), None)
            ok = job["status"] == "succeeded" and mp4 and Path(mp4["abs_path"]).exists()
            if not ok:
                typer.echo(f"\n✗ warmup FAILED: status={job['status']} error={job.get('error')}")
                raise typer.Exit(1)
            typer.echo(f"\n✓ warmup OK in {time.time() - t0:.1f}s → {mp4['abs_path']} "
                       f"({mp4.get('duration_seconds')}s · {mp4['size_bytes']} bytes)")
        finally:
            if jid and not keep:
                shutil.rmtree(settings.workspaces_dir / jid, ignore_errors=True)
                await repo.db.execute("DELETE FROM jobs WHERE id=?", (jid,))
                await repo.db.commit()
            await repo.close()

    asyncio.run(_go())


@app.command()
def fonts(verify: bool = typer.Option(False, "--verify")) -> None:
    settings = get_settings()
    fdir = settings.vendor_dir / "fonts"
    if verify:
        ok = any(fdir.glob("*.otf")) or any(fdir.glob("*.ttf"))
        typer.echo(f"OFL CJK font present: {ok} ({fdir})")
        raise typer.Exit(0 if ok else 1)
    fonts_present = sorted(p.name for p in list(fdir.glob("*.otf")) + list(fdir.glob("*.ttf")))
    typer.echo(f"OFL CJK font is vendored at {fdir}: {fonts_present or 'MISSING — run `make bootstrap`'}")
    typer.echo("Subsetting happens per-job (fonts stage); use `monoline fonts --verify` to check.")


def _ensure_frontend_built(settings) -> None:
    index = settings.static_dir / "index.html"
    if index.exists():
        return
    typer.echo("frontend not built — building web/dist (first run may take ~30s)...")
    try:
        subprocess.run(["pnpm", "--filter", "@monoline/web", "build"], check=True, cwd=str(settings.repo_root))
    except Exception as e:  # noqa: BLE001
        typer.echo(f"⚠ frontend build failed ({e}); API still runs. Open the JSON at /api/health.")


if __name__ == "__main__":
    app()
