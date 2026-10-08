"use client";

import Link from "next/link";
import { useRef } from "react";
import { motion, useScroll, useTransform } from "motion/react";
import { useLenis } from "lenis/react";
import PlantVideo from "./PlantVideo";
import RevealLines from "./motion/RevealLines";
import Reveal from "./motion/Reveal";
import { useIntroDone } from "./motion/Providers";
import { easeOut } from "./motion/easing";
import { contactHref, contactLabel, site } from "@/lib/site";

export default function HomeHero() {
  const ref = useRef<HTMLElement>(null);
  const introDone = useIntroDone();
  const lenis = useLenis();

  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end start"] });
  const imageY = useTransform(scrollYProgress, [0, 1], ["0%", "22%"]);
  const contentY = useTransform(scrollYProgress, [0, 1], ["0%", "-35%"]);
  const contentOpacity = useTransform(scrollYProgress, [0, 0.6], [1, 0]);

  return (
    <section ref={ref} className="relative h-svh min-h-[640px] overflow-hidden">
      <motion.div className="absolute inset-0 will-change-transform" style={{ y: imageY }}>
        <motion.div
          className="absolute inset-0 will-change-transform"
          initial={{ transform: "scale(1.25)" }}
          animate={{ transform: introDone ? "scale(1.05)" : "scale(1.25)" }}
          transition={{ duration: 2.4, ease: easeOut }}
        >
          <PlantVideo />
        </motion.div>
      </motion.div>

      <div aria-hidden="true" className="absolute inset-0 bg-gradient-to-r from-paper via-paper/80 to-paper/0" />
      <div aria-hidden="true" className="absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-paper/90 to-transparent" />
      <div aria-hidden="true" className="absolute inset-x-0 top-0 h-40 bg-gradient-to-b from-paper/80 to-transparent" />

      <motion.div
        style={{ y: contentY, opacity: contentOpacity }}
        className="relative mx-auto flex h-full max-w-7xl flex-col justify-end px-6 pb-14 will-change-transform lg:px-12 lg:pb-20"
      >
        <RevealLines
          as="p"
          start={introDone}
          delay={0.2}
          className="text-xs font-semibold uppercase tracking-[0.3em] text-accent-deep"
          lines={[site.tagline]}
        />

        <RevealLines
          as="h1"
          start={introDone}
          delay={0.3}
          className="mt-6 text-[clamp(2.1rem,5.2vw,5.25rem)] font-semibold uppercase leading-[0.92] tracking-[-0.035em]"
          lines={[
            "Every system and",
            "each process component,",
            <span key="mirrored">
              <span className="text-accent">mirrored</span> in real time.
            </span>,
          ]}
        />

        <div className="mt-10 flex flex-col gap-8 sm:flex-row sm:items-end sm:justify-between">
          <Reveal start={introDone} delay={0.8} y={20} className="max-w-xl">
            <p className="text-lg leading-relaxed text-ink/70">
              {site.name} creates digital twins of critical unit operations and process equipment — helping chemical
              plants predict failures, save energy and run at their best.
            </p>
            <Link
              href={contactHref}
              className="mt-6 inline-flex items-center rounded-full border border-line bg-surface/90 px-6 py-3 text-sm font-medium transition-colors hover:border-accent hover:text-accent-deep"
            >
              {contactLabel}
            </Link>
          </Reveal>

          <Reveal start={introDone} delay={1} y={20}>
            <button
              type="button"
              onClick={() => lenis?.scrollTo("footer", { duration: 1.6 })}
              aria-label="Scroll down"
              className="group flex h-14 w-14 items-center justify-center rounded-full border border-ink/20 bg-surface/85 transition-colors hover:border-accent hover:bg-accent hover:text-white"
            >
              <svg viewBox="0 0 24 24" className="h-5 w-5 transition-transform duration-500 group-hover:translate-y-0.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M12 5v14M6 13l6 6 6-6" />
              </svg>
            </button>
          </Reveal>
        </div>
      </motion.div>
    </section>
  );
}
