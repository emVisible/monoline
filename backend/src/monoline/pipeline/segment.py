"""Segmentation strategy — turn arbitrary pasted text into well-sized beats.

The M1 failure was "one line = one beat": a pasted paragraph became a single
37s wall-of-text caption. This splits into sentence-level beats with a length
budget, while RESPECTING the user's explicit line breaks as strong boundaries.

Pluggable: `Segmenter` protocol; `SentenceSegmenter` is the v1 (only) impl.
LLM semantic segmentation can drop in later behind the same interface.
"""
from __future__ import annotations

import re
from typing import Protocol

# Sentence-final punctuation (CJK + latin). Keep the mark attached to the beat.
# Latin "." splits only when followed by whitespace → decimals ("3.14", "$5.5") stay intact.
# NOTE: ；/; are NOT sentence-final — they separate clauses (e.g. "命中：68%；覆盖：42%"),
# so splitting there would shred structured k:v lines into single-number fragments.
_SENT_SPLIT = re.compile(r"(?<=[。！？!?…])|(?<=\.)(?=\s)")
# Secondary split for over-long sentences (clause boundaries, incl. semicolons).
_CLAUSE_SPLIT = re.compile(r"(?<=[，,、：:；;])")
_WS = re.compile(r"\s+")
# Leading markdown/list markers people paste (headers "# ", bullets "- • ·", "1."/"2)"/"1、").
# Stripped so the marker never leaks into a headline/caption/TTS and "2. x" isn't misread
# as a stat. Requires trailing whitespace → leaves "3.14", "-10%" and "C#" intact.
_LIST_MARK = re.compile(r"^\s*(?:#{1,6}|[-*+•·‣⁃]|\d+[.)、])\s+")


class Segmenter(Protocol):
    def segment(self, text: str) -> list[str]: ...


class SentenceSegmenter:
    """min/target/max are in CJK-equivalent characters (latin runs count loosely)."""

    def __init__(self, *, min_chars: int = 6, target_chars: int = 24, max_chars: int = 40,
                 max_beats: int = 60) -> None:
        self.min_chars = min_chars
        self.target_chars = target_chars
        self.max_chars = max_chars
        self.max_beats = max_beats

    def _len(self, s: str) -> int:
        return len(_WS.sub("", s))

    def _split_long(self, s: str) -> list[str]:
        """Recursively split an over-budget sentence on clause punctuation."""
        if self._len(s) <= self.max_chars:
            return [s]
        parts = [p for p in _CLAUSE_SPLIT.split(s) if p and p.strip()]
        if len(parts) <= 1:
            return [s]  # no clause boundary; keep as-is (a long word/number)
        # greedily re-pack clauses to <= max_chars
        out: list[str] = []
        cur = ""
        for p in parts:
            if cur and self._len(cur) + self._len(p) > self.max_chars:
                out.append(cur)
                cur = p
            else:
                cur = (cur + p) if cur else p
        if cur:
            out.append(cur)
        # any single clause still too long stays (rare)
        return out

    def segment(self, text: str) -> list[str]:
        beats: list[str] = []
        for line in text.splitlines():
            line = _LIST_MARK.sub("", line.strip(), count=1)
            if not line:
                continue
            # explicit line break = strong boundary; split the line into sentences
            sentences = [s.strip() for s in _SENT_SPLIT.split(line) if s and s.strip()]
            for sent in sentences:
                beats.extend(self._split_long(sent))
        beats = self._merge_tiny(beats)
        if len(beats) > self.max_beats:
            raise ValueError(f"{len(beats)} beats exceeds cap {self.max_beats}; split the script into shorter pieces")
        return beats

    def _join(self, a: str, b: str) -> str:
        """Concatenate two beats. Latin runs need a space between them; CJK does not
        (CJK chars are non-ASCII, so an ASCII boundary on both sides means latin)."""
        if a and b and a[-1].isascii() and not a[-1].isspace() and b[0].isascii() and not b[0].isspace():
            return a + " " + b
        return a + b

    def _merge_tiny(self, beats: list[str]) -> list[str]:
        """Fold a beat shorter than min_chars into its neighbour (prefer previous)."""
        out: list[str] = []
        for b in beats:
            if out and self._len(b) < self.min_chars and self._len(out[-1]) + self._len(b) <= self.max_chars + self.min_chars:
                out[-1] = self._join(out[-1], b)
            elif out and self._len(out[-1]) < self.min_chars:
                out[-1] = self._join(out[-1], b)  # previous was tiny; absorb current into it
            else:
                out.append(b)
        # trailing fragment
        if len(out) >= 2 and self._len(out[-1]) < self.min_chars:
            out[-2] = self._join(out[-2], out[-1])
            out.pop()
        return out


def segment_text(text: str, **kw: object) -> list[str]:
    return SentenceSegmenter(**kw).segment(text)  # type: ignore[arg-type]
