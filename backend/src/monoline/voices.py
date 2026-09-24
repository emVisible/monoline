"""Voice registry (V8) — the curated set of built-in TTS voices + audition samples.

Kokoro ships 12 voices; the phonemizer language is derived from the voice-id prefix
(a=en-us, b=en-gb, e=es, f=fr-fr, j=ja, z=zh). A job therefore stores voice AND lang
together — picking a voice sets the matching lang so TTS never mismatches them. This
module is the single source of truth for which voices we expose and how they're grouped.
"""
from __future__ import annotations

# id = the exact --voice arg; lang = the --phonemizer-lang it needs; group = UI bucket.
VOICES: list[dict] = [
    {"id": "af_heart",   "label": "Heart",    "lang": "en-us", "group": "English (US)", "gender": "f"},
    {"id": "af_nova",    "label": "Nova",     "lang": "en-us", "group": "English (US)", "gender": "f"},
    {"id": "af_sky",     "label": "Sky",      "lang": "en-us", "group": "English (US)", "gender": "f"},
    {"id": "am_adam",    "label": "Adam",     "lang": "en-us", "group": "English (US)", "gender": "m"},
    {"id": "am_michael", "label": "Michael",  "lang": "en-us", "group": "English (US)", "gender": "m"},
    {"id": "bf_emma",    "label": "Emma",     "lang": "en-gb", "group": "English (UK)", "gender": "f"},
    {"id": "bf_isabella","label": "Isabella", "lang": "en-gb", "group": "English (UK)", "gender": "f"},
    {"id": "bm_george",  "label": "George",   "lang": "en-gb", "group": "English (UK)", "gender": "m"},
    {"id": "ef_dora",    "label": "Dora",     "lang": "es",    "group": "Español", "gender": "f"},
    {"id": "ff_siwis",   "label": "Siwis",    "lang": "fr-fr", "group": "Français", "gender": "f"},
    {"id": "jf_alpha",   "label": "Alpha",    "lang": "ja",    "group": "日本語", "gender": "f"},
    {"id": "zf_xiaobei", "label": "Xiaobei",  "lang": "zh",    "group": "中文", "gender": "f"},
]

DEFAULT_VOICE = "zf_xiaobei"

# One short line per phonemizer language, played when the user auditions a voice.
SAMPLE_TEXT: dict[str, str] = {
    "en-us": "Hi, this is how I sound.",
    "en-gb": "Hello, this is how I sound.",
    "es":    "Hola, así es como sueno.",
    "fr-fr": "Bonjour, voilà ma voix.",
    "ja":    "こんにちは、これが私の声です。",
    "zh":    "你好，这就是我朗读的声音。",
}

_BY_ID = {v["id"]: v for v in VOICES}


def available() -> list[dict]:
    """The voice list for the API (defensive copy; order is the UI order)."""
    return [dict(v) for v in VOICES]


def is_known_voice(voice: str | None) -> bool:
    return bool(voice) and voice in _BY_ID


def voice_lang(voice: str) -> str | None:
    """The phonemizer lang a voice needs, or None if unknown."""
    v = _BY_ID.get(voice)
    return v["lang"] if v else None


def sample_text(voice: str) -> str:
    """Audition line for a voice (falls back to the default voice's language)."""
    lang = voice_lang(voice) or _BY_ID[DEFAULT_VOICE]["lang"]
    return SAMPLE_TEXT.get(lang, SAMPLE_TEXT["en-us"])
