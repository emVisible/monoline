"""sceneplan/v1 — the meaning layer. Replaces generate.py's hardcoded `stage` list.

Monochrome is enforced structurally: there is NO per-scene color field. Slots may
carry a `tone` ∈ {ink, muted, accent} resolved through the theme tokens. A validator
rejects >1 accent per screen. This is how "ultra-minimal high-end gray" survives a
pluggable-template layer.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA = "sceneplan/v1"

# Full M2 kind registry. Each kind = one Jinja partial + a slot spec in kinds.json.
# `statement` is the safe default. V27 adds the diagram kinds (`flow` / `radial` /
# `steps`) built from the shared `.node` graphic atom — content that renders as a
# picture (nodes + connectors) instead of a line of text.
KINDS = ["title", "statement", "section", "definition", "stat", "table",
         "cards", "compare", "quote", "list", "note", "summary", "image",
         "flow", "radial", "steps"]
# Kinds whose whole payload is already drawn as graphics on the slide — the caption
# would just repeat the node labels, so the planner marks them verbatim.
DIAGRAM_KINDS = {"flow", "radial", "steps"}
KINDS_M1 = set(KINDS)  # validate_against accepts the full set as of M2
Tone = Literal["ink", "muted", "accent"]


class Canvas(BaseModel):
    width: int = 1920
    height: int = 1080
    fps: int = 30


class Theme(BaseModel):
    """Loaded from design/tokens/*.json — shared with the web UI."""

    id: str
    label: str = ""
    mode: Literal["dark", "light"] = "dark"
    tokens: dict[str, Any] = Field(default_factory=dict)

    @property
    def color(self) -> dict[str, str]:
        return self.tokens.get("color", {})

    @property
    def motion(self) -> dict[str, Any]:
        return self.tokens.get("motion", {})

    @property
    def space(self) -> dict[str, Any]:
        return self.tokens.get("space", {})


class Brand(BaseModel):
    label: str = "Monoline"
    logo: str = ""            # composition-relative image path (assets/…); empty = text-only brand
    show_eyebrow_date: bool = True


class Captions(BaseModel):
    mode: Literal["sentence", "auto_chunk", "none"] = "sentence"
    chunk_max_chars: int = 22
    track_index: int = 3


class Scene(BaseModel):
    model_config = ConfigDict(extra="allow")
    i: int
    kind: str
    source: str = "manual"  # rules:<pattern> | manual | llm — provenance badge in UI
    slots: dict[str, Any] = Field(default_factory=dict)
    layout: dict[str, Any] | None = None
    motion: dict[str, Any] | None = None
    fallback_kind: str = "statement"

    def tone_of(self, slot: str) -> Tone:
        v = self.slots.get(slot)
        return v.get("tone", "ink") if isinstance(v, dict) else "ink"


class ScenePlan(BaseModel):
    schema_: str = SCHEMA
    job_id: str = ""
    canvas: Canvas = Field(default_factory=Canvas)
    theme: Theme
    brand: Brand = Field(default_factory=Brand)
    captions: Captions = Field(default_factory=Captions)
    scenes: list[Scene] = Field(default_factory=list)

    def validate_against(self, n_segments: int) -> list[str]:
        """Return warnings (non-blocking); raises on hard violations."""
        warnings: list[str] = []
        if len(self.scenes) != n_segments:
            raise ValueError(
                f"scene count ({len(self.scenes)}) != segment count ({n_segments})"
            )
        for s in self.scenes:
            if s.kind not in KINDS_M1:
                warnings.append(f"scene {s.i}: kind '{s.kind}' not in M1 set {sorted(KINDS_M1)}")
            if s.i != self.scenes.index(s):
                warnings.append(f"scene index {s.i} out of order")
        # accent budget: ≤1 accent tone per scene across its slots
        for s in self.scenes:
            accents = [k for k in s.slots if isinstance(s.slots[k], dict) and s.slots[k].get("tone") == "accent"]
            if len(accents) > 1:
                warnings.append(f"scene {s.i}: {len(accents)} accent slots (budget 1)")
        return warnings
