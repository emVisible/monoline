"""Narration text → what a voice should actually say (V30).

Two problems this fixes, both measured:

1. Spoken punctuation. Anything that is not Hanzi is routed to an English G2P, and
   espeak happily spells symbols out: a bare `%` came back as `pɚsˈɛnt` ("percent")
   and `**` as `ˈæstɚɹˌsk…` ("asterisk asterisk"). Markdown leftovers, emoji and
   diagram glyphs (→) must never reach the model as letters.

2. Metronome delivery. One flat speed for every beat reads as a recitation. Rate is
   now chosen from the line's own shape (a number-heavy line gets room to land; a
   long plain sentence runs slightly quicker), and the pauses between clauses and
   sentences are widened into a breath rather than a click.
"""
from __future__ import annotations

import re

# Dashes / arrows / ellipses are breaths, never words. A long one keeps its own mark so
# _phrasing can give it the longer gap; a short one collapses to a comma.
_LONGISH = re.compile(r"…+|[—–―]{2,}")
_SHORTISH = re.compile(r"[—–―]|[" + "".join(chr(c) for c in (0x2192, 0x21D2, 0x279C, 0x27A6)) + r"]|-{1,2}>|=>")
# Symbols a G2P will spell out. Kept as a class so nothing sneaks through.
_SPELL = re.compile(r"[*_~`#^|\\\\<>\u2605\u2606\u25cf\u2022\u2027\u00b7\u2023\u25b8\u2192\u2713\u2714\u261e\u261f]+")
# Emoji and other supplementary-plane pictographs (espeak names several of them).
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]+")
# Fullwidth percent → ASCII so the Chinese normalizer reads "92%" as 百分之九十二.
_FW_PCT = re.compile("％")
# A % with no number in front of it is a typo, not "percent".
_BARE_PCT = re.compile(r"(?<![0-9.])%+")
_DUP_COMMA = re.compile(r"[，,]{2,}")
_TRAIL_COMMA = re.compile(r"[，,]\s*([。！？!?])")

# Breaths, in seconds of real silence. Kokoro's own sentence_pause/clause_pause are
# useless here: with is_phonemes=True a comma is not a stop, so a whole line arrives as
# one batch and gets no internal pause at all. We split by clause and insert the gap.
GAP_CLAUSE = 0.20      # ，、；
GAP_SENTENCE = 0.42    # 。！？
GAP_LONG = 0.62        # … or a dash — the "let that land" beat
GAP_HEAD = 0.05
GAP_TAIL = 0.24
# Silence kept from the end of each rendered chunk, so our gap adds to it instead of
# stacking on top of whatever the model already trailed off with.
TRAIL_KEEP = 0.05


def clean(text: str) -> str:
    """Strip everything that would be spelled out; turn dashes/arrows into pauses."""
    s = _FW_PCT.sub("%", text or "")
    s = _LONGISH.sub("……", s)
    s = _SHORTISH.sub("，", s)
    s = _EMOJI.sub("", s)
    s = _SPELL.sub("", s)
    s = _BARE_PCT.sub("", s)
    s = _DUP_COMMA.sub("，", s)
    s = _TRAIL_COMMA.sub(r"\1", s)
    return re.sub(r"[ \t]{2,}", " ", s).strip()


_DIGITS = re.compile(r"[0-9]+(?:[.,][0-9]+)?")


def rate(text: str) -> float:
    """Per-line speaking rate. Numbers need room to land; long prose can run.

    Bounded to Kokoro's supported 0.5-2.0 and kept near 1.0 so durations stay sane.
    """
    t = clean(text)
    n = len(re.sub(r"\s", "", t))
    if n == 0:
        return 1.0
    digits = sum(len(m.group(0)) for m in _DIGITS.finditer(t))
    if digits / n > 0.25 or n <= 8:          # a stat-like line: slow it down
        return 0.90
    if n >= 34:                              # a long sentence: a touch quicker
        return 1.04
    return 0.97
