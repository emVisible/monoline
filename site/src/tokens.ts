// The design language is imported from the product, not copied: `design/tokens/ui.json` is
// the same file the app's stylesheet is derived from, so the marketing page cannot quietly
// drift to a different grey. A Vercel build of a stale palette would otherwise look fine and
// lie forever. (The path is relative to THIS file, hence ../../ — site/src/ → repo root.)
import type { Easing } from "motion/react";
import raw from "../../design/tokens/ui.json";

interface UiTokens {
  color: Record<string, string>;
  type: {
    family_ui: string;
    scale_px: number[];
    leading_body: number;
    measure_ch: number;
    eyebrow: { transform: string; tracking: string };
    display_tracking: string;
  };
  space_px: number[];
  radii_px: number[];
  motion: {
    durations_ms: Record<string, number>;
    ease: Record<string, string>;
    translate_px: number[];
    stagger_ms: Record<string, number>;
  };
}

const t = raw as unknown as UiTokens;

// One deliberate tripwire: everything downstream assumes these nine exist.
for (const key of ["paper", "surface", "elev", "hairline", "ink", "ink_muted", "ink_faint", "accent", "accent_ink"]) {
  if (!t.color[key]?.startsWith("#")) throw new Error(`ui.json lost colour token "${key}"`);
}

export const c = t.color;
export const motion = t.motion;

/** Type scale, largest first — the page reads it as "display / h2 / body / label". */
const scale = [...t.type.scale_px].reverse();          // [60, 42, 30, 24, 20, 17, 14, 12]
export const px = (n: number) => `${n}px`;
export const display = px(scale[0]);
export const h2 = px(scale[1]);

const vars: Record<string, string> = {
  "--paper": c.paper,
  "--surface": c.surface,
  "--elev": c.elev,
  "--hairline": c.hairline,
  "--ink": c.ink,
  "--ink-muted": c.ink_muted,
  "--ink-faint": c.ink_faint,
  "--accent": c.accent,
  "--accent-ink": c.accent_ink,
  "--font-ui": t.type.family_ui,
  "--leading-body": String(t.type.leading_body),
  "--measure": `${t.type.measure_ch}ch`,
  "--eyebrow-tracking": t.type.eyebrow.tracking,
  "--display-tracking": t.type.display_tracking,
  "--d-micro": `${t.motion.durations_ms.micro}ms`,
  "--d-element": `${t.motion.durations_ms.element}ms`,
  "--d-surface": `${t.motion.durations_ms.surface}ms`,
  "--d-scene": `${t.motion.durations_ms.scene}ms`,
  "--ease-out": t.motion.ease.out_quart,
  "--ease-inout": t.motion.ease.in_out_soft,
};
t.type.scale_px.forEach((n, i) => { vars[`--t${i}`] = px(n); });
t.space_px.forEach((n, i) => { vars[`--sp${i}`] = px(n); });
t.radii_px.forEach((n, i) => { vars[`--r${i}`] = px(n); });

export function injectTokens(): void {
  const style = document.createElement("style");
  style.id = "monoline-tokens";
  style.textContent = `:root{${Object.entries(vars).map(([k, v]) => `${k}:${v}`).join(";")}}`;
  document.head.appendChild(style);
}

/** Motion values in seconds, because `motion` takes seconds and the tokens are in ms. */
export const dur = {
  micro: t.motion.durations_ms.micro / 1000,
  element: t.motion.durations_ms.element / 1000,
  surface: t.motion.durations_ms.surface / 1000,
  scene: t.motion.durations_ms.scene / 1000,
};
/** The token file stores a cubic-bezier() string; `motion` wants the same string typed as an
 *  Easing. One cast at the boundary keeps every call site honest instead of scattering `as any`. */
export const easeOut = t.motion.ease.out_quart as Easing;
export const easeInOut = t.motion.ease.in_out_soft as Easing;
export const staggerBase = t.motion.stagger_ms.base / 1000;
