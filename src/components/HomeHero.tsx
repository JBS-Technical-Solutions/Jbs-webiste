"use client";

import { useRef } from "react";
import { motion, useScroll, useTransform } from "motion/react";
import { useLenis } from "lenis/react";
import PlantVideo from "./PlantVideo";
import RevealLines from "./motion/RevealLines";
import Reveal from "./motion/Reveal";
import { useIntroDone } from "./motion/Providers";
import { easeOut } from "./motion/easing";
import { phoneHref, site } from "@/lib/site";

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
      <motion.div className="absolute inset-0" style={{ y: imageY }}>
        <motion.div
          className="absolute inset-0"
          initial={{ scale: 1.25 }}
          animate={{ scale: introDone ? 1.05 : 1.25 }}
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
        className="relative mx-auto flex h-full max-w-7xl flex-col justify-end px-6 pb-14 lg:px-12 lg:pb-20"
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
          className="mt-6 text-[clamp(2.6rem,6.5vw,6.5rem)] font-semibold uppercase leading-[0.92] tracking-[-0.035em]"
          lines={[
            "Every critical",
            <span key="mirrored">
              machine, <span className="text-accent">mirrored</span>
            </span>,
            "in real time.",
          ]}
        />

        <div className="mt-10 flex flex-col gap-8 sm:flex-row sm:items-end sm:justify-between">
          <Reveal start={introDone} delay={0.8} y={20} className="max-w-xl">
            <p className="text-lg leading-relaxed text-ink/70">
              {site.name} creates digital twins of critical process equipment — helping chemical plants predict
              failures, save energy and run at their best.
            </p>
            <a
              href={phoneHref}
              className="mt-6 inline-flex items-center rounded-full border border-line bg-white/80 px-6 py-3 text-sm font-medium backdrop-blur transition-colors hover:border-accent hover:text-accent-deep"
            >
              {site.phone}
            </a>
          </Reveal>

          <Reveal start={introDone} delay={1} y={20}>
            <button
              type="button"
              onClick={() => lenis?.scrollTo("footer", { duration: 1.6 })}
              aria-label="Scroll down"
              className="group flex h-14 w-14 items-center justify-center rounded-full border border-ink/20 bg-white/60 backdrop-blur transition-colors hover:border-accent hover:bg-accent hover:text-white"
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
