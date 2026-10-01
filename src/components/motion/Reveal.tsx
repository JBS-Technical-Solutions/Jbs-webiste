"use client";

import { motion } from "motion/react";
import type { ReactNode } from "react";
import { easeOut } from "./easing";

type Props = {
  children: ReactNode;
  className?: string;
  delay?: number;
  y?: number;
  /** When omitted, the content reveals as it scrolls into view. */
  start?: boolean;
};

export default function Reveal({ children, className, delay = 0, y = 32, start }: Props) {
  const hidden = { opacity: 0, y };
  const visible = { opacity: 1, y: 0 };
  const trigger =
    start === undefined
      ? { whileInView: visible, viewport: { once: true, margin: "0px 0px -10% 0px" } }
      : { animate: start ? visible : hidden };

  return (
    <motion.div className={className} initial={hidden} transition={{ duration: 1, delay, ease: easeOut }} {...trigger}>
      {children}
    </motion.div>
  );
}
