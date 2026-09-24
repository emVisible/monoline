import { useCallback, useEffect, useRef, useState } from "react";

export type Voice = { id: string; label: string; lang: string; group: string; gender: string };

/** Load the curated voice registry once, plus the server-designated default. */
export function useVoices(): { voices: Voice[]; default: string } {
  const [state, setState] = useState<{ voices: Voice[]; default: string }>({ voices: [], default: "" });
  useEffect(() => {
    fetch("/api/voices").then((r) => r.json())
      .then((d) => setState({ voices: d.voices || [], default: d.default || "" })).catch(() => {});
  }, []);
  return state;
}

/** Bucket voices by their language group, preserving server order. */
export function groupVoices(voices: Voice[]): { name: string; items: Voice[] }[] {
  const out: { name: string; items: Voice[] }[] = [];
  for (const v of voices) {
    let g = out.find((x) => x.name === v.group);
    if (!g) { g = { name: v.group, items: [] }; out.push(g); }
    g.items.push(v);
  }
  return out;
}

/**
 * Audition voices via the cached /sample endpoint. Only one plays at a time; toggling
 * the active id stops it. `loadingId` covers the first-synth delay (the server renders
 * an unheard voice on demand, ~2–5s) so the caller can show a spinner until audio starts.
 */
export function useAudition() {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [loadingId, setLoadingId] = useState<string | null>(null);

  const stop = useCallback(() => {
    audioRef.current?.pause();
    audioRef.current = null;
    setPlayingId(null);
    setLoadingId(null);
  }, []);

  const toggle = useCallback((id: string) => {
    if (playingId === id) { stop(); return; }
    audioRef.current?.pause();
    const a = new Audio(`/api/voices/${id}/sample`);
    audioRef.current = a;
    setLoadingId(id);
    a.addEventListener("playing", () => setLoadingId(null));
    a.addEventListener("ended", () => { if (audioRef.current === a) stop(); });
    a.addEventListener("error", () => { if (audioRef.current === a) stop(); });
    a.play().catch(() => { if (audioRef.current === a) stop(); });
    setPlayingId(id);
  }, [playingId, stop]);

  useEffect(() => () => { audioRef.current?.pause(); }, []);
  return { playingId, loadingId, toggle, stop };
}
