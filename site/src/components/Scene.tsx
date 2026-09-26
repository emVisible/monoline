import { motion, useInView, useReducedMotion } from "motion/react";
import { useRef } from "react";
import type { ReactNode } from "react";
import { dur, easeOut, staggerBase } from "../tokens";

/**
 * One screen of the page is one "scene", borrowing the product's own furniture: dot-grid wash,
 * two corner brackets, an eyebrow label, a folio counter and a hairline rule. The page is
 * laid out the way the tool lays out a film, which is the whole conceit — so it lives in one
 * component rather than being repeated per section.
 */
export function Scene({
  index, total, eyebrow, children, align = "left", id,
}: {
  index: number; total: number; eyebrow: string; children: ReactNode;
  align?: "left" | "center"; id?: string;
}) {
  // `once` is load-bearing: without it a scene animates back out when it leaves the viewport,
  // so scrolling up showed a blank page (caught by a full-page capture, not by a viewport one).
  const ref = useRef<HTMLElement | null>(null);
  const inView = useInView(ref, { margin: "-25% 0px -25% 0px", once: true });
  const reduced = useReducedMotion();

  const group = {
    hidden: { opacity: 0, y: reduced ? 0 : 28 },
    show: {
      opacity: 1, y: 0,
      transition: { duration: reduced ? 0.12 : dur.scene, ease: easeOut, delayChildren: staggerBase },
    },
  };
  const item = {
    hidden: { opacity: 0, y: reduced ? 0 : 16 },
    show: { opacity: 1, y: 0, transition: { duration: reduced ? 0.12 : dur.surface, ease: easeOut } },
  };

  return (
    <motion.section
      ref={ref} id={id} className={`scene scene--${align}`} data-index={index}
      initial="hidden" animate={inView ? "show" : "hidden"} variants={group}
    >
      <span className="scene__wash" aria-hidden="true" />
      <span className="bracket bracket--tl" aria-hidden="true" />
      <span className="bracket bracket--br" aria-hidden="true" />
      <motion.p className="eyebrow" variants={item}>{eyebrow}</motion.p>
      {children}
      <motion.div className="folio" variants={item} aria-hidden="true">
        <span className="folio__now">{String(index + 1).padStart(2, "0")}</span>
        <span className="folio__sep">/</span>
        <span>{String(total).padStart(2, "0")}</span>
      </motion.div>
    </motion.section>
  );
}

export function Rule() {
  const ref = useRef<HTMLSpanElement | null>(null);
  const inView = useInView(ref, { margin: "-20% 0px", once: true });
  return (
    <span ref={ref} className="rule" aria-hidden="true"
      style={{ transform: inView ? "scaleX(1)" : "scaleX(0)" }} />
  );
}

export function Lead({ children }: { children: ReactNode }) {
  return <p className="lead">{children}</p>;
}

export function Note({ children }: { children: ReactNode }) {
  return <p className="note">{children}</p>;
}
