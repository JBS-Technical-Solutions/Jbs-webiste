"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";
import { useLenis } from "lenis/react";
import EquipmentDiagram from "./EquipmentDiagram";
import { easeInOut, easeOut } from "./motion/easing";
import { contactHref, contactLabel } from "@/lib/site";
import { models, type EquipmentModel } from "@/lib/models";

function LoadingSimulation() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 text-white/70">
      <span className="h-10 w-10 animate-spin rounded-full border-2 border-white/15 border-t-accent" />
      <p className="text-xs font-semibold uppercase tracking-[0.25em]">Loading simulation</p>
    </div>
  );
}

const HeatExchangerTwin = dynamic(() => import("./hx/HeatExchangerTwin"), {
  ssr: false,
  loading: LoadingSimulation,
});

const MethanolTwin = dynamic(() => import("./meoh/MethanolTwin"), {
  ssr: false,
  loading: LoadingSimulation,
});

const SIMULATIONS: Partial<Record<EquipmentModel["slug"], typeof HeatExchangerTwin>> = {
  "heat-exchanger": HeatExchangerTwin,
  "methanol-reformer": MethanolTwin,
};

const order: EquipmentModel["slug"][] = ["heat-exchanger", "pump", "methanol-reformer"];
const launchModels = order.map((slug) => models.find((m) => m.slug === slug)!);

export default function TwinLauncher() {
  const [active, setActive] = useState<EquipmentModel | null>(null);
  const close = useCallback(() => setActive(null), []);
  const [simulating, setSimulating] = useState<EquipmentModel | null>(null);
  const closeSimulation = useCallback(() => setSimulating(null), []);

  return (
    <>
      <div className="grid gap-5 md:grid-cols-3">
        {launchModels.map((model, i) => (
          <motion.div
            key={model.slug}
            initial={{ opacity: 0, transform: "translateY(32px)" }}
            whileInView={{ opacity: 1, transform: "translateY(0px)" }}
            viewport={{ once: true, margin: "0px 0px -10% 0px" }}
            transition={{ duration: 0.9, delay: 0.1 * i, ease: easeOut }}
            className="relative flex flex-col overflow-hidden rounded-3xl border border-line bg-surface transition-colors duration-500 has-[button:hover]:border-accent/60"
          >
            <button
              type="button"
              onClick={() => setActive(model)}
              aria-haspopup="dialog"
              className="group flex flex-1 flex-col text-left"
            >
              <div className="relative aspect-[4/3] w-full bg-soft p-6 transition-colors duration-500 group-hover:bg-accent-soft">
                <span className="absolute left-5 top-5 font-mono text-xs text-muted">0{i + 1}</span>
                <span
                  aria-hidden="true"
                  className="absolute right-4 top-4 flex h-11 w-11 items-center justify-center rounded-full border border-line bg-surface text-lg transition-all duration-500 group-hover:rotate-45 group-hover:border-accent group-hover:bg-accent group-hover:text-white"
                >
                  +
                </span>
                <EquipmentDiagram kind={model.slug} label={`${model.name} schematic`} />
              </div>
              <div className="w-full flex-1 p-6 pb-5">
                <p className="text-[11px] font-semibold uppercase tracking-[0.25em] text-accent-deep">{model.category}</p>
                <h3 className="mt-2 text-2xl font-semibold uppercase tracking-tight">{model.name}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">{model.summary}</p>
              </div>
            </button>
            <div className="px-6 pb-6">
              <button
                type="button"
                onClick={() => setSimulating(model)}
                aria-haspopup="dialog"
                aria-label={`${model.name} simulation`}
                className="group/sim flex w-full items-center justify-between rounded-full bg-accent px-5 py-3.5 text-xs font-semibold uppercase tracking-[0.18em] text-white transition-colors duration-300 hover:bg-accent-deep"
              >
                <span className="flex items-center gap-3">
                  <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="currentColor" aria-hidden="true">
                    <path d="M7 4.5v15a1 1 0 0 0 1.5.86l12-7.5a1 1 0 0 0 0-1.72l-12-7.5A1 1 0 0 0 7 4.5Z" />
                  </svg>
                  Simulation
                </span>
                <span aria-hidden="true" className="transition-transform duration-300 group-hover/sim:translate-x-1">
                  →
                </span>
              </button>
            </div>
          </motion.div>
        ))}
      </div>

      <TwinModal model={active} onClose={close} />
      <SimulationModal model={simulating} onClose={closeSimulation} />
    </>
  );
}

function useDialog(open: boolean, onClose: () => void) {
  const lenis = useLenis();
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    lenis?.stop();
    const previous = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      lenis?.start();
      window.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, [open, lenis, onClose]);

  return closeRef;
}

function SimulationModal({ model, onClose }: { model: EquipmentModel | null; onClose: () => void }) {
  const closeRef = useDialog(!!model, onClose);
  const Simulation = model ? SIMULATIONS[model.slug] : null;

  return (
    <AnimatePresence>
      {model && (
        <motion.div
          key="simulation-modal"
          role="dialog"
          aria-modal="true"
          aria-labelledby="simulation-title"
          className="fixed inset-0 z-[70] flex flex-col bg-black"
          initial={{ clipPath: "inset(100% 0% 0% 0%)" }}
          animate={{ clipPath: "inset(0% 0% 0% 0%)" }}
          exit={{ clipPath: "inset(100% 0% 0% 0%)" }}
          transition={{ duration: 0.8, ease: easeInOut }}
        >
          <div className="flex items-center justify-between gap-4 border-b border-white/10 px-4 py-3 text-white sm:px-6">
            <div className="flex min-w-0 items-center gap-3">
              <span className="relative flex h-2 w-2 shrink-0">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-60" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-accent" />
              </span>
              <p id="simulation-title" className="truncate text-xs font-semibold uppercase tracking-[0.25em]">
                {model.name} · Digital twin simulation
              </p>
            </div>
            <button
              ref={closeRef}
              type="button"
              onClick={onClose}
              className="flex shrink-0 items-center gap-2 rounded-full border border-white/20 px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] transition-colors hover:border-accent hover:bg-accent"
            >
              Close
              <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </div>

          <div data-lenis-prevent className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
            {Simulation ? (
              <Simulation className="min-h-full" />
            ) : (
              <WorkInProgress model={model} onClose={onClose} />
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function WorkInProgress({ model, onClose }: { model: EquipmentModel; onClose: () => void }) {
  return (
    <motion.div
      className="flex min-h-full flex-col items-center justify-center px-6 py-16 text-center text-white"
      initial="hidden"
      animate="visible"
      variants={{ visible: { transition: { staggerChildren: 0.08, delayChildren: 0.5 } } }}
    >
      <Item>
        <span className="inline-flex items-center gap-2 rounded-full border border-accent/40 bg-accent/10 px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.25em] text-accent">
          <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-accent/30 border-t-accent" aria-hidden="true" />
          Work in progress
        </span>
      </Item>
      <Item>
        <p className="mt-8 text-xs font-semibold uppercase tracking-[0.3em] text-white/50">{model.category}</p>
      </Item>
      <Item>
        <h2 className="mt-3 text-[clamp(2.25rem,6vw,4.5rem)] font-semibold uppercase leading-[0.92] tracking-[-0.035em]">
          {model.name}
        </h2>
      </Item>
      <Item>
        <p className="mx-auto mt-6 max-w-xl leading-relaxed text-white/65">
          We&apos;re building the live simulation for this digital twin. It will be available here soon — in the
          meantime, talk to us about twinning your {model.name.toLowerCase()}.
        </p>
      </Item>
      <Item>
        <Link
          href={contactHref}
          onClick={onClose}
          className="mt-10 inline-block rounded-full bg-accent px-6 py-3 text-xs font-semibold uppercase tracking-[0.18em] text-white transition-colors hover:bg-accent-deep"
        >
          {contactLabel}
        </Link>
      </Item>
    </motion.div>
  );
}

function TwinModal({ model, onClose }: { model: EquipmentModel | null; onClose: () => void }) {
  const closeRef = useDialog(!!model, onClose);

  return (
    <AnimatePresence>
      {model && (
        <motion.div
          key="twin-modal"
          className="fixed inset-0 z-[60] flex items-end justify-center sm:items-center sm:p-6"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0, transition: { duration: 0.4, delay: 0.2 } }}
          transition={{ duration: 0.4 }}
        >
          <div aria-hidden="true" onClick={onClose} className="absolute inset-0 bg-black/70 backdrop-blur-sm" />

          <motion.div
            role="dialog"
            aria-modal="true"
            aria-labelledby="twin-modal-title"
            className="relative flex max-h-[92svh] w-full max-w-5xl flex-col overflow-hidden rounded-t-3xl bg-paper shadow-2xl sm:rounded-3xl"
            initial={{ clipPath: "inset(100% 0% 0% 0% round 24px)", y: 40 }}
            animate={{ clipPath: "inset(0% 0% 0% 0% round 24px)", y: 0 }}
            exit={{ clipPath: "inset(100% 0% 0% 0% round 24px)", y: 40 }}
            transition={{ duration: 0.8, ease: easeInOut }}
          >
            <button
              ref={closeRef}
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="absolute right-4 top-4 z-10 flex h-11 w-11 items-center justify-center rounded-full border border-line bg-surface/80 backdrop-blur transition-colors hover:border-accent hover:bg-accent hover:text-white sm:right-6 sm:top-6"
            >
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>

            <div data-lenis-prevent className="grid min-h-0 overflow-y-auto overflow-x-hidden md:grid-cols-2 lg:grid-cols-[1.1fr_1fr]">
              <div className="bg-soft">
                <div className="relative flex aspect-[16/10] items-center px-8 pb-4 pt-14 md:sticky md:top-0 md:aspect-auto md:h-[min(92svh,600px)] md:p-10 lg:p-12">
                  <span className="absolute left-6 top-6 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.25em] text-muted sm:left-8 sm:top-8">
                    <span className="relative flex h-2 w-2">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-60" />
                      <span className="relative inline-flex h-2 w-2 rounded-full bg-accent" />
                    </span>
                    Digital twin · live
                  </span>
                  <motion.div
                    key={model.slug}
                    className="w-full"
                    initial={{ opacity: 0, scale: 0.94 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ duration: 0.9, delay: 0.35, ease: easeOut }}
                  >
                    <EquipmentDiagram kind={model.slug} label={`${model.name} schematic`} />
                  </motion.div>
                </div>
              </div>

              <motion.div
                className="p-8 sm:p-10"
                initial="hidden"
                animate="visible"
                variants={{ visible: { transition: { staggerChildren: 0.07, delayChildren: 0.45 } } }}
              >
                <Item>
                  <p className="text-xs font-semibold uppercase tracking-[0.3em] text-accent-deep">{model.category}</p>
                </Item>
                <Item>
                  <h2
                    id="twin-modal-title"
                    className="mt-4 pr-12 text-[clamp(2rem,4vw,3.25rem)] font-semibold uppercase leading-[0.92] tracking-[-0.035em]"
                  >
                    {model.name}
                  </h2>
                </Item>
                <Item>
                  <p className="mt-5 leading-relaxed text-muted">{model.description}</p>
                </Item>
                <Item>
                  <h3 className="mt-8 text-xs font-semibold uppercase tracking-[0.25em]">What it tracks</h3>
                  <ul className="mt-3 flex flex-wrap gap-2">
                    {model.tracks.map((item) => (
                      <li key={item} className="rounded-full border border-line bg-surface px-3 py-1.5 text-[13px]">
                        {item}
                      </li>
                    ))}
                  </ul>
                </Item>
                <Item>
                  <h3 className="mt-8 text-xs font-semibold uppercase tracking-[0.25em]">What you get</h3>
                  <ul className="mt-3 space-y-1.5">
                    {model.outcomes.map((item) => (
                      <li key={item} className="flex gap-3 text-[15px]">
                        <span aria-hidden="true" className="text-accent">→</span>
                        {item}
                      </li>
                    ))}
                  </ul>
                </Item>
                <Item>
                  <div className="mt-10 flex flex-wrap gap-3">
                    <Link
                      href={contactHref}
                      onClick={onClose}
                      className="rounded-full bg-accent px-6 py-3 text-xs font-semibold uppercase tracking-[0.18em] text-white transition-colors hover:bg-accent-deep"
                    >
                      {contactLabel}
                    </Link>
                  </div>
                </Item>
              </motion.div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function Item({ children }: { children: ReactNode }) {
  return (
    <motion.div
      variants={{
        hidden: { opacity: 0, y: 20 },
        visible: { opacity: 1, y: 0, transition: { duration: 0.7, ease: easeOut } },
      }}
    >
      {children}
    </motion.div>
  );
}
