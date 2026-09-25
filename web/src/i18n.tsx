import { Fragment, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { EN } from "./strings";

export type Lang = "zh" | "en";
const KEY = "monoline.lang";

// Language is module state, not React state, so `t()` is a plain function: it can be called
// from render bodies, helpers and object lookups without threading a hook through every
// component. Correct because switching language remounts the tree (LangRoot keys a fragment),
// so a reader that never subscribed still re-evaluates.
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

export function LangRoot({ children }: { children: ReactNode }) {
  const [v, bump] = useState(0);
  useEffect(() => {
    reroot = () => bump((n) => n + 1);
    return () => { reroot = null; };
  }, []);
  return <Fragment key={v}>{children}</Fragment>;
}
