"""LLM script-writing client (V1) — provider-agnostic, OpenAI-compatible.

Works with any /chat/completions endpoint: OpenAI, or a local Ollama/LM Studio
via MONOLINE_LLM_BASE_URL. Emits narration text (one beat per line) that feeds
straight into the existing segment→plan→render pipeline. Never blocks the loop.
"""
from __future__ import annotations

import re

import httpx

from ..settings import Settings

# beats target by requested length
_LENGTH_BEATS = {"short": (6, 8), "medium": (10, 14), "long": (16, 22)}
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
                          length: str = "medium", lang: str = "zh", timeout: float = 60) -> str:
    if not settings.llm_ready:
        raise LLMNotConfigured("LLM 未配置：设置 MONOLINE_LLM_API_KEY 或指向本地 Ollama")
    if not topic.strip():
        raise LLMError("主题为空")
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    headers = {"content-type": "application/json"}
    if settings.llm_api_key:
        headers["authorization"] = f"Bearer {settings.llm_api_key}"
    body = {"model": settings.llm_model, "messages": build_messages(topic, tone=tone, length=length, lang=lang),
            "temperature": 0.8}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=body, headers=headers)
    except httpx.HTTPError as e:
        raise LLMError(f"LLM 请求失败：{e}") from e
    if resp.status_code >= 400:
        raise LLMError(f"LLM 返回 {resp.status_code}：{resp.text[:200]}")
    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"LLM 响应结构异常：{str(data)[:200]}") from e
    script = _clean(content)
    if not script:
        raise LLMError("LLM 返回空内容")
    return script
