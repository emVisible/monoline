"""Mandarin synthesis that keeps its lexical tones.

kokoro-onnx phonemizes Chinese with espeak-ng, which writes tones as *digits*
(`妈` -> `m` + `a` + tone 5). Kokoro's vocabulary is 114 symbols and contains no
digits at all, and `Tokenizer.phonemize` silently drops every character outside it —
so 妈/马/骂 all reach the model as the identical string, and 师/诗/史/市 as one.
Toneless Mandarin is exactly what "every Chinese voice sounds like a dialect" is:
the loss happens before the speaker embedding, so no voice choice can fix it.

misaki's ZHG2P emits the tone contours the model was actually trained on
(-> / rising / dipping / falling arrows, all in-vocab), so Chinese runs through it
and straight into kokoro-onnx via `is_phonemes=True`. Latin runs go to espeak
`en-us` instead: misaki passes them through raw and most ASCII letters are not in
the vocabulary either.
"""
from __future__ import annotations

import re
from pathlib import Path

# Same location the HyperFrames CLI downloads to (~/.cache/hyperframes/tts).
_TTS_CACHE = Path.home() / ".cache" / "hyperframes" / "tts"
MODEL = _TTS_CACHE / "models" / "kokoro-v1.0.onnx"
VOICES = _TTS_CACHE / "voices" / "voices-v1.0.bin"

# CJK punctuation, ideographs (incl. ext. A + compatibility) — everything misaki can
# read as Chinese. Built from code points so the ranges stay legible.
_CJK_RANGES = ((0x3005, 0x3007), (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF))
# The capture group is load-bearing: re.split only returns the separators it matched
# when the pattern captures them, and the separators here are the Chinese runs.
_CJK = re.compile("([" + "".join(f"{chr(a)}-{chr(b)}" for a, b in _CJK_RANGES) + "]+)")
# Our planner emits beats like "需求->设计->开发" for flow scenes; the arrow is a
# diagram glyph, so it must become a pause rather than be read out loud.
_ARROW = re.compile("[" + "".join(chr(c) for c in (0x2192, 0x21D2, 0x279C, 0x27A6)) + "]|-{1,2}>|=>")

_engine: dict = {}


def _g2p() -> dict:
    """Load the tone-carrying G2P (no model weights needed)."""
    if "g2p" not in _engine:
        from kokoro_onnx.tokenizer import Tokenizer
        from misaki import zh

        _engine["g2p"] = zh.ZHG2P()
        _engine["en"] = Tokenizer()  # espeak-backed, for Latin runs only
    return _engine


def _load() -> dict | None:
    """Load the ONNX engine, or None when this path can't run on this machine."""
    if "k" in _engine:
        return _engine
    if not (MODEL.exists() and VOICES.exists()):
        return None
    try:
        import soundfile  # noqa: F401
        from kokoro_onnx import Kokoro

        _g2p()
        _engine["k"] = Kokoro(str(MODEL), str(VOICES))
    except Exception:  # noqa: BLE001 — missing dep / unreadable model = fall back
        return None
    return _engine


def status() -> str:
    """"ok" | "will_download" (G2P present, model not cached yet) | "missing"."""
    if _load() is not None:
        return "ok"
    try:
        _g2p()
    except Exception:  # noqa: BLE001
        return "missing"
    return "missing" if (MODEL.exists() and VOICES.exists()) else "will_download"


def available() -> bool:
    """True when the tone-correct path can actually synthesize.

    The CLI fetches the model files on first use, so a cold machine starts on the
    espeak fallback and upgrades itself to this path once they exist.
    """
    return status() == "ok"


def phonemize(text: str) -> str:
    """Hanzi -> Kokoro phonemes with tone contours; interleaved Latin -> en-us phonemes."""
    eng = _g2p()
    from cn2an import transform
    from misaki import zh as _zh

    text = _ARROW.sub("，", text.strip())
    text = transform(text, "an2cn")          # "3倍" -> 三倍, "92%" -> 百分之九十二
    text = _zh.ZHG2P.map_punctuation(text)   # 。，！？ -> ASCII (in-vocab pauses)
    out: list[str] = []
    for seg in _CJK.split(text):
        if not seg:
            continue
        out.append(eng["g2p"].legacy_call(seg) if _CJK.fullmatch(seg) else eng["en"].phonemize(seg, "en-us"))
    return " ".join(p for p in out if p.strip())


def synthesize(text: str, voice: str, out_wav: str, *, speed: float = 1.0) -> float:
    """Write one line to `out_wav`; return its duration in seconds."""
    import soundfile as sf

    eng = _load()
    if eng is None:
        raise RuntimeError("tone-correct zh engine unavailable")
    phones = phonemize(text)
    if not phones.strip():
        raise ValueError(f"no phonemes for {text!r}")
    audio, sr = eng["k"].create(phones, voice, speed, is_phonemes=True)
    sf.write(out_wav, audio, sr)
    return len(audio) / sr


def synthesize_file(text_file: str, out_wav: str, *, voice: str, speed: float = 1.0) -> float:
    return synthesize(Path(text_file).read_text(encoding="utf-8"), voice, out_wav, speed=speed)
