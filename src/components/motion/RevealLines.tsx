"use client";

import { motion, type Variants } from "motion/react";
import type { ReactNode } from "react";
import { easeOut } from "./easing";

const tags = {
  h1: motion.h1,
  h2: motion.h2,
  h3: motion.h3,
  p: motion.p,
  div: motion.div,
};

type Props = {
  lines: ReactNode[];
  as?: keyof typeof tags;
  className?: string;
  delay?: number;
  stagger?: number;
  /** When omitted, the lines reveal as they scroll into view. */
  start?: boolean;
};

export default function RevealLines({ lines, as = "div", className, delay = 0, stagger = 0.09, start }: Props) {
  const Tag = tags[as];

  const container: Variants = {
    hidden: {},
    visible: { transition: { staggerChildren: stagger, delayChildren: delay } },
  };
  const line: Variants = {
    hidden: { transform: "translateY(110%)" },
    visible: { transform: "translateY(0%)", transition: { duration: 1, ease: easeOut } },
  };

  const trigger =
    start === undefined
      ? { whileInView: "visible", viewport: { once: true, margin: "0px 0px -10% 0px" } }
      : { animate: start ? "visible" : "hidden" };

  return (
    <Tag className={className} variants={container} initial="hidden" {...trigger}>
      {lines.map((content, i) => (
        <span key={i} className="-mb-[0.12em] block overflow-hidden pb-[0.12em]">
          <motion.span className="block" variants={line}>
            {content}
          </motion.span>
        </span>
      ))}
    </Tag>
  );
}
