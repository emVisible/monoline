import { motion, useScroll, useSpring, useTransform } from "motion/react";
import type { MotionValue } from "motion/react";

/**
 * The page's scroll position IS the playhead: the same accent rail the video paints at the
 * bottom of every frame. Scroll drives it, and the ticks are the scene boundaries, so "where
 * am I in the piece" is answered with the product's own furniture.
 */
export function Playhead({ scenes }: { scenes: number }) {
  const { scrollYProgress } = useScroll();
  const width = useSpring(scrollYProgress, { stiffness: 120, damping: 30, mass: 0.4 });
  const position = useTransform(width, (v) => v * scenes);

  return (
    <div className="playhead" aria-hidden="true">
      <div className="playhead__ticks">
        {Array.from({ length: scenes }, (_, i) => <Tick key={i} index={i} position={position} />)}
      </div>
      <motion.div className="playhead__fill" style={{ scaleX: width }} />
    </div>
  );
}

function Tick({ index, position }: { index: number; position: MotionValue<number> }) {
  const opacity = useTransform(position, (n) => (n > index + 0.12 ? 1 : 0.25));
  return <motion.span className="playhead__tick" style={{ opacity }} />;
}
