import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import hero from "../hero.json";
import { dur, easeOut, staggerBase } from "../tokens";
import { t } from "../i18n";

/**
 * The hero is the product's central act, performed: a paragraph cuts itself into beats.
 *
 * The data is not authored for this page — `hero.json` is a dump of the real segmenter and
 * rule planner (`monoline.pipeline.segment.segment_text` + `RulePlanner().plan`) run over the
 * text shown. Re-deriving it is one command (see site/README.md). A hand-written fake here
 * would be the same mistake the app already deleted: a second, simpler implementation of
 * segmentation living in the frontend.
 */
export function HeroCut() {
  const reduced = useReducedMotion();
  const [shown, setShown] = useState(reduced ? hero.beats.length : 0);
  const [run, setRun] = useState(0);

  useEffect(() => {
    if (reduced) { setShown(hero.beats.length); return; }
    setShown(0);
    const timers = hero.beats.map((_, i) =>
      window.setTimeout(() => setShown(i + 1), 500 + i * 320));
    return () => timers.forEach(clearTimeout);
  }, [reduced, run]);

  // The source split by sentence-final punctuation: when the counts agree, beat i is the cut
  // of sentence i, and the sentence can be marked as it is consumed.
  const sentences = useMemo(() => splitSentences(hero.source), []);
  const mappable = sentences.length === hero.beats.length;

  return (
    <div className="cut">
      <div className="cut__col">
        <span className="cut__label">{t("demo_source_label")}</span>
        <p className="cut__source" aria-label={hero.source}>
          {mappable
            ? sentences.map((s, i) => (
                <span key={i} className="cut__sent" data-cut={shown > i || undefined}>{s}</span>
              ))
            : <span>{hero.source}</span>}
        </p>
        <button className="cut__replay" type="button" onClick={() => setRun((n) => n + 1)}>
          ⟳ {t("demo_caption")}
        </button>
      </div>

      <div className="cut__col">
        <span className="cut__label">{t("demo_beats_label")}</span>
        <ol className="cut__beats">
          <AnimatePresence initial={false}>
            {hero.beats.slice(0, shown).map((b, i) => (
              <motion.li
                key={`${run}-${i}`} className="beat" data-kind={b.kind}
                initial={reduced ? false : { opacity: 0, x: 18 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: reduced ? 0 : dur.surface, ease: easeOut }}
              >
                <span className="beat__no">{String(i + 1).padStart(2, "0")}</span>
                <span className="beat__text">{b.text}</span>
                <span className="beat__kind">{b.kind}</span>
              </motion.li>
            ))}
          </AnimatePresence>
          {shown < hero.beats.length && (
            <motion.li className="beat beat--pending"
              animate={{ opacity: [0.2, 0.55, 0.2] }}
              transition={{ duration: 1.1, repeat: Infinity, ease: "linear" }}
            >
              <span className="beat__no">··</span>
              <span className="beat__text">…</span>
            </motion.li>
          )}
        </ol>
      </div>
    </div>
  );
}

function splitSentences(text: string): string[] {
  const parts = text.match(/[^。！？…]+[。！？…]?/g) ?? [];
  return parts.map((p) => p.trim()).filter(Boolean);
}

/** Kept exported for the kinds grid so both halves share one timing constant. */
export const beatStagger = staggerBase;
