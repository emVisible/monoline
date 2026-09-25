"""LLM client (V1 script writing, V29 storyboard upgrade) — OpenAI-compatible.

Works with any /chat/completions endpoint: OpenAI, or a local Ollama / LM Studio.
Unconfigured → we still probe a local Ollama, because "I started Ollama" is the
common case for a local-only tool and env vars are the uncommon one.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass

import httpx

from ..settings import Settings, get_settings

# beats target by requested length
_LENGTH_BEATS = {"short": (6, 8), "medium": (10, 14), "long": (16, 22)}
OLLAMA_URL = os.environ.get("MONOLINE_OLLAMA_URL", "http://127.0.0.1:11434")
_PROBE_TTL = 15.0  # seconds; keeps page loads from hammering the model server
_CACHE: tuple[float, Target] | None = None
_TONE = {
    "neutral": "克制、专业、陈述事实",
    "warm": "有温度、口语化、亲切",
    "punchy": "短促有力、有节奏、抓人",
    "witty": "机智、有梗、轻松",
}


class LLMError(RuntimeError):
    pass


class LLMNotConfigured(LLMError):
    pass


@dataclass
class Target:
    """Where to send a completion request, and how we know it's alive."""

    base_url: str = ""
    model: str = ""
    api_key: str = ""
    source: str = "none"          # "env" (MONOLINE_LLM_*) | "ollama" (auto-detected) | "none"
    ok: bool = False
    detail: str = ""
    latency_ms: int | None = None

    def as_dict(self) -> dict:
        return {"ready": self.ok, "source": self.source, "model": self.model or None,
                "base_url": self.base_url or None, "detail": self.detail, "latency_ms": self.latency_ms}


def _ollama_models(timeout: float = 2.0) -> tuple[list[str], str, int | None]:
    """Model ids served by the local Ollama, plus an error string and probe latency."""
    t0 = time.monotonic()
    try:
        r = httpx.get(OLLAMA_URL.rstrip("/") + "/api/tags", timeout=timeout)
    except Exception as e:  # noqa: BLE001 — any transport problem means "not connected"
        return [], f"{type(e).__name__}: {e}", None
    if r.status_code >= 400:
        return [], f"HTTP {r.status_code}", None
    models = [m.get("model", "") for m in r.json().get("models", []) if m.get("model")]
    return models, "", int((time.monotonic() - t0) * 1000)


def detect(settings: Settings | None = None, *, force: bool = False) -> Target:
    """Resolve the LLM target: explicit env config wins, else a live local Ollama.

    Cached for _PROBE_TTL so opening a page doesn't hit the model server every render.
    """
    global _CACHE
    now = time.monotonic()
    if not force and _CACHE and now - _CACHE[0] < _PROBE_TTL:
        return _CACHE[1]

    settings = settings or get_settings()
    if settings.llm_ready:
        t = Target(base_url=settings.llm_base_url, model=settings.llm_model,
                   api_key=settings.llm_api_key, source="env")
        t = _verify_env(t)
    else:
        models, err, ms = _ollama_models()
        if not models:
            t = Target(source="none", detail=f"未检测到本地 Ollama（{OLLAMA_URL}）" + (f"：{err}" if err else ""))
        else:
            want = os.environ.get("MONOLINE_LLM_MODEL", "")
            t = Target(base_url=OLLAMA_URL.rstrip("/") + "/v1",
                       model=want if want in models else models[0],
                       source="ollama", ok=True, latency_ms=ms,
                       detail=f"{len(models)} 个本地模型可选" if want in models or len(models) == 1
                              else f"从 {len(models)} 个模型里取了第一个")
    _CACHE = (now, t)
    return t


def _verify_env(t: Target) -> Target:
    """A configured remote endpoint is only 'connected' if it answers /models."""
    t0 = time.monotonic()
    try:
        headers = {"authorization": f"Bearer {t.api_key}"} if t.api_key else {}
        r = httpx.get(t.base_url.rstrip("/") + "/models", headers=headers, timeout=5.0)
    except Exception as e:  # noqa: BLE001
        t.detail = f"{type(e).__name__}: {e}"
        return t
    t.latency_ms = int((time.monotonic() - t0) * 1000)
    if r.status_code >= 400:
        t.detail = f"HTTP {r.status_code}"
        return t
    t.ok = True
    t.detail = "endpoint reachable"
    return t


async def chat(messages: list[dict], *, target: Target | None = None, temperature: float = 0.8,
               json_mode: bool = False, timeout: float = 120.0) -> str:
    """One completion. Raises LLMNotConfigured / LLMError; never returns empty."""
    t = target or detect()
    if not t.ok or not t.base_url:
        raise LLMNotConfigured(t.detail or "LLM 未配置：设置 MONOLINE_LLM_* 或启动本地 Ollama")
    body: dict = {"model": t.model, "messages": messages, "temperature": temperature, "stream": False}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    headers = {"content-type": "application/json"}
    if t.api_key:
        headers["authorization"] = f"Bearer {t.api_key}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(t.base_url.rstrip("/") + "/chat/completions", json=body, headers=headers)
    except httpx.HTTPError as e:
        raise LLMError(f"LLM 请求失败：{e}") from e
    if resp.status_code >= 400:
        raise LLMError(f"LLM 返回 {resp.status_code}：{resp.text[:200]}")
    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"LLM 响应结构异常：{str(data)[:200]}") from e
    if not (content or "").strip():
        raise LLMError("LLM 返回空内容")
    return content


def parse_json(text: str) -> object:
    """Tolerant JSON read: models wrap the payload in fences or an outer object."""
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s).rsplit("```", 1)[0].strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"[\[{].*[\]}]", s, re.S)
        if not m:
            raise LLMError(f"LLM 未返回 JSON：{s[:120]}")
        return json.loads(m.group(0))


def list_as(value: object) -> list:
    """Unwrap the `{key: [...]}` shell some models return instead of a bare array."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for v in value.values():
            if isinstance(v, list):
                return v
    return []


def build_messages(topic: str, *, tone: str, length: str, lang: str) -> list[dict]:
    lo, hi = _LENGTH_BEATS.get(length, _LENGTH_BEATS["medium"])
    tone_desc = _TONE.get(tone, _TONE["neutral"])
    lang_name = "中文" if lang == "zh" else "English"
    sys = (
        f"你是短视频旁白撰稿人。用{lang_name}写作，风格：{tone_desc}。"
        f"把主题写成一段适合逐拍配音的口播稿，规则："
        f"1) 每行一个完整短句/一拍，共 {lo}-{hi} 行；"
        f"2) 只输出正文，不要编号、项目符号、Markdown、引号、标题；"
        f"3) 句子口语自然、信息密度高、避免空话套话；"
        f"4) 首行点题、末行收束。"
    )
    return [{"role": "system", "content": sys}, {"role": "user", "content": topic.strip()}]


def _clean(text: str) -> str:
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        s = re.sub(r"^[0-9]+[.)、]\s*", "", s)          # "1." "2)" "3、"
        s = re.sub(r"^[-*•]\s+", "", s)                 # bullet
        s = s.strip("*_`#> ").strip("\"'“”‘’").strip()  # markdown emphasis / quotes
        if s:
            out.append(s)
    return "\n".join(out)


async def generate_script(settings: Settings, topic: str, *, tone: str = "neutral",
                          length: str = "medium", lang: str = "zh", timeout: float = 180) -> str:
    """Topic → narration script (one beat per line). Works off env config or a local Ollama."""
    if not topic.strip():
        raise LLMError("主题为空")
    content = await chat(build_messages(topic, tone=tone, length=length, lang=lang),
                         target=detect(settings), temperature=0.8, timeout=timeout)
    script = _clean(content)
    if not script:
        raise LLMError("LLM 返回空内容")
    return script
