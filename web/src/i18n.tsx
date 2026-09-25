import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { EN } from "./strings";

export type Lang = "zh" | "en";
const KEY = "monoline.lang";

// Language is module state, not React state, so `t()` is a plain function: it can be called
// from render bodies, helpers and object lookups without threading a hook through every
// component. Correct because LangRoot re-renders the whole tree on a language change, so a
// reader that never subscribed still re-evaluates.
let current: Lang = readStored();
let reroot: (() => void) | null = null;

function readStored(): Lang {
  try {
    return localStorage.getItem(KEY) === "en" ? "en" : "zh";
  } catch {
    return "zh";                       // private mode / file:// without storage
  }
}

export function lang(): Lang { return current; }

export function t(s: string): string {
  return current === "en" ? (EN[s] ?? s) : s;
}

export function setLang(next: Lang) {
  if (next === current) return;
  current = next;
  try { localStorage.setItem(KEY, next); } catch { /* session only */ }
  applyHtmlLang(next);
  reroot?.();
}

export function applyHtmlLang(l: Lang) {
  document.documentElement.lang = l === "zh" ? "zh-CN" : "en";
}

export function LangRoot({ children }: { children: () => ReactNode }) {
  const [, bump] = useState(0);
  useEffect(() => {
    reroot = () => bump((n) => n + 1);
    return () => { reroot = null; };
  }, []);
  // children is called, not embedded, so a language change produces fresh elements for the
  // whole tree and every component re-reads t(). Keying a fragment achieved the same repaint
  // by REMOUNTING, and that destroyed state: measured, switching language wiped a 958-char
  // script already typed into the compose box.
  return <>{children()}</>;
}
