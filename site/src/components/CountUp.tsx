import { useEffect, useRef, useState } from "react";
import { animate, useInView, useReducedMotion } from "motion/react";
import { easeOut } from "../tokens";

/**
 * Count-up, the same signature the product uses when a `stat` beat lands. It reports the real
 * value in the DOM at rest (the animated number is decorative), so a screen reader or a
 * no-JS view never sees a wrong figure.
 */
export function CountUp({ to, suffix = "" }: { to: number; suffix?: string }) {
  const ref = useRef<HTMLSpanElement | null>(null);
  const inView = useInView(ref, { margin: "-20% 0px", once: true });
  const reduced = useReducedMotion();
  const [n, setN] = useState(reduced ? to : 0);
  const done = useRef(false);

  useEffect(() => {
    if (!inView || reduced || done.current) return;
    done.current = true;
    const controls = animate(0, to, {
      duration: 0.9, ease: easeOut, onUpdate: (v) => setN(Math.round(v)),
    });
    return () => controls.stop();
  }, [inView, reduced, to]);

  return (
    <span className="count" ref={ref}>
      <span className="count__n">{n}</span>
      <span className="count__suffix">{suffix}</span>
      <span className="sr-only">{to}{suffix}</span>
    </span>
  );
}
