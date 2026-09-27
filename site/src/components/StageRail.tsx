import { useRef } from "react";
import { motion, useInView, useReducedMotion } from "motion/react";
import { dur, easeOut } from "../tokens";
import { STAGES } from "../strings";
import { lang, t } from "../i18n";

/** The nine stages as the product draws a timeline: a rail that draws itself, nodes on it. */
export function StageRail() {
  const ref = useRef<HTMLOListElement | null>(null);
  const inView = useInView(ref, { margin: "-25% 0px", once: true });
  const reduced = useReducedMotion();

  return (
    <ol ref={ref} className="rail" aria-label={t("rail_aria")}>
      <motion.span className="rail__line" aria-hidden="true"
        initial={{ scaleX: 0 }} animate={inView ? { scaleX: 1 } : {}}
        transition={{ duration: reduced ? 0 : dur.scene * 1.6, ease: easeOut }} />
      {STAGES.map((s, i) => (
        <motion.li key={s.en} className="rail__node"
          initial={reduced ? false : { opacity: 0, y: 10 }}
          animate={inView ? { opacity: 1, y: 0 } : {}}
          transition={{ duration: reduced ? 0 : dur.surface, ease: easeOut, delay: 0.25 + i * 0.06 }}
        >
          <span className="rail__dot" aria-hidden="true" />
          <span className="rail__no">{String(i + 1).padStart(2, "0")}</span>
          <span className="rail__name">{lang() === "zh" ? s.zh : s.en}</span>
        </motion.li>
      ))}
    </ol>
  );
}
