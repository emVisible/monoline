import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { STRINGS } from "./strings";

export type Lang = "en" | "zh";
const KEY = "monoline.site.lang";

// Same shape as the app's i18n: language is module state so `t()` is a plain function, and
// LangRoot re-renders the whole tree on a switch. The app learned the hard way that keying a
// fragment to force the repaint REMOUNTS everything and destroys typed input — here that would
// restart the hero cut mid-animation, so children is called, not embedded.
let current: Lang = readStored();
let reroot: (() => void) | null = null;

function readStored(): Lang {
  try {
    const s = localStorage.getItem(KEY);
    if (s === "en" || s === "zh") return s;
  } catch { /* private mode */ }
  return navigator.language?.toLowerCase().startsWith("zh") ? "zh" : "en";
}

export function lang(): Lang { return current; }

export function t(id: keyof typeof STRINGS): string { return STRINGS[id][current]; }

export function setLang(next: Lang): void {
  if (next === current) return;
  current = next;
  try { localStorage.setItem(KEY, next); } catch { /* session only */ }
  document.documentElement.lang = next === "zh" ? "zh-CN" : "en";
  reroot?.();
}

export function LangRoot({ children }: { children: () => ReactNode }) {
  const [, bump] = useState(0);
  useEffect(() => {
    reroot = () => bump((n) => n + 1);
    document.documentElement.lang = current === "zh" ? "zh-CN" : "en";
    return () => { reroot = null; };
  }, []);
  return <>{children()}</>;
}
