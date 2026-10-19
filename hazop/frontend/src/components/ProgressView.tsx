"use client";

import clsx from "clsx";
import { Check, FileText, LoaderCircle, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { imageUrl } from "@/lib/api";
import type { Job } from "@/lib/types";
import { Button, Card, Logo } from "./ui";

const TIPS = [
  "Text is read in overlapping tiles, then vertical labels are re-read in both rotations.",
  "Instrument bubbles are paired letter-over-number (e.g. TSHH over 2850B) per ISA 5.1.",
  "Line numbers are decoded as size-service-spec-number-insulation and checked against piping specs.",
  "Design pressure is compared with the piping class rating to find overpressure scenarios.",
  "Safeguards are only credited when the instrument or device is actually on the drawing.",
  "First run on a new drawing takes longest — results are cached for repeat runs.",
];

export default function ProgressView({ job, onCancel }: { job: Job; onCancel: () => void }) {
  const [elapsed, setElapsed] = useState(0);
  const [tip, setTip] = useState(0);
  const [imgReady, setImgReady] = useState(false);
  const [imgKey, setImgKey] = useState(0);

  useEffect(() => {
    const t0 = Date.now();
    const id = setInterval(() => setElapsed((Date.now() - t0) / 1000), 500);
    const tipId = setInterval(() => setTip((t) => (t + 1) % TIPS.length), 5000);
    return () => {
      clearInterval(id);
      clearInterval(tipId);
    };
  }, []);

  const stageIndex = useMemo(() => job.stages.findIndex((s) => s.id === job.stage), [job.stages, job.stage]);
  const pct = Math.round(job.progress * 100);
  const pastRender = stageIndex >= job.stages.findIndex((s) => s.id === "ocr");

  return (
    <div className="flex min-h-screen flex-col bg-slate-50">
      <header className="border-b border-slate-200 bg-white/80 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-4 sm:px-8">
          <Logo />
          <Button variant="ghost" size="sm" onClick={onCancel}>
            <X className="h-4 w-4" /> Cancel
          </Button>
        </div>
      </header>

      <main className="mx-auto grid w-full max-w-6xl flex-1 items-center gap-8 px-5 py-10 sm:px-8 lg:grid-cols-[1.3fr_1fr]">
        {/* Drawing preview with scan effect */}
        <Card className="relative overflow-hidden p-3">
          <div className="relative aspect-[17/11] overflow-hidden rounded-xl bg-slate-900">
            <div className="bg-grid-dark absolute inset-0" />
            {pastRender && (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                key={imgKey}
                src={`${imageUrl(`/api/jobs/${job.id}/image`)}?v=${imgKey}`}
                alt="Uploaded P&ID"
                onLoad={() => setImgReady(true)}
                onError={() => setTimeout(() => setImgKey((k) => k + 1), 1500)}
                className={clsx(
                  "absolute inset-0 h-full w-full bg-white object-contain transition-opacity duration-700",
                  imgReady ? "opacity-100" : "opacity-0",
                )}
              />
            )}
            {!imgReady && (
              <div className="absolute inset-0 grid place-items-center">
                <div className="flex flex-col items-center gap-3 text-slate-400">
                  <FileText className="h-10 w-10 animate-float text-brand-300" />
                  <span className="text-xs">Preparing drawing…</span>
                </div>
              </div>
            )}
            {job.status !== "done" && (
              <div className="pointer-events-none absolute inset-x-0 h-24 animate-scan">
                <div className="h-full w-full bg-gradient-to-b from-transparent via-brand-500/25 to-transparent" />
                <div className="absolute inset-x-0 top-1/2 h-px bg-brand-400 shadow-[0_0_16px_4px_rgba(59,99,246,0.6)]" />
              </div>
            )}
          </div>
          <div className="flex items-center justify-between px-2 pb-1 pt-3">
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-slate-900">{job.filename}</div>
              <div className="text-xs text-slate-500">
                {job.options.mode === "ai" ? "Rule engine + AI review" : "Rule engine"} &middot; {elapsed.toFixed(0)}s elapsed
              </div>
            </div>
            <div className="text-right">
              <div className="text-2xl font-semibold tabular-nums text-slate-900">{pct}%</div>
            </div>
          </div>
          <div className="mx-2 mb-2 h-2 overflow-hidden rounded-full bg-slate-100">
            <motion.div
              className="relative h-full rounded-full bg-gradient-to-r from-brand-500 via-brand-400 to-cyan-400"
              animate={{ width: `${Math.max(3, pct)}%` }}
              transition={{ ease: "easeOut", duration: 0.6 }}
            >
              <div className="shimmer absolute inset-0" />
            </motion.div>
          </div>
        </Card>

        {/* Stepper */}
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Analysing your P&amp;ID</h1>
          <p className="mt-1 text-sm text-slate-500">You can keep this tab open — the worksheet appears automatically.</p>
          {job.detail && <p className="mt-2 text-sm font-medium text-brand-700">{job.detail}</p>}
          {job.checks && (
            <div className="mt-4 rounded-2xl bg-white p-4 ring-1 ring-slate-200">
              <div className="flex items-baseline justify-between gap-3">
                <div className="text-[11px] font-semibold uppercase tracking-wider text-brand-600">Drawings checked</div>
                <div className="text-xs font-medium tabular-nums text-slate-500">
                  {job.checks.verified} of {job.checks.drawings} verified
                </div>
              </div>
              <p className="mt-1 text-sm text-slate-700">
                {job.checks.drawings} drawing{job.checks.drawings === 1 ? "" : "s"} in {job.checks.files} file
                {job.checks.files === 1 ? "" : "s"}. Each PDF page is counted, then every drawing is opened.
              </p>
              <ul className="mt-3 max-h-40 space-y-1.5 overflow-auto">
                {job.checks.items.map((item, index) => (
                  <li key={`${item.name}-${index}`} className="flex items-center justify-between gap-3 text-xs">
                    <span className="min-w-0 truncate font-medium text-slate-800" title={item.name}>
                      {item.name}
                    </span>
                    <span className="shrink-0 tabular-nums text-slate-500">
                      {item.kind === "pdf" ? "PDF" : "Image"} · {item.pages} page{item.pages === 1 ? "" : "s"}
                      {item.status === "checking" ? ` · ${item.verified}/${item.pages}` : ""}
                      {item.status === "ok" ? " · verified" : ""}
                      {item.status === "partial" ? " · some pages failed" : ""}
                      {item.status === "unreadable" ? " · could not open" : ""}
                      {item.status === "skipped" ? " · over the 500 limit" : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <ol className="mt-7 space-y-1">
            {job.stages.map((s, i) => {
              const done = i < stageIndex || job.status === "done";
              const active = i === stageIndex && job.status !== "done";
              return (
                <li key={s.id} className="relative flex gap-4 pb-5 last:pb-0">
                  {i < job.stages.length - 1 && (
                    <span
                      className={clsx(
                        "absolute left-[15px] top-8 h-[calc(100%-24px)] w-0.5 rounded-full transition-colors duration-500",
                        done ? "bg-brand-500" : "bg-slate-200",
                      )}
                    />
                  )}
                  <span
                    className={clsx(
                      "relative z-10 grid h-8 w-8 shrink-0 place-items-center rounded-full ring-4 ring-slate-50 transition-all duration-300",
                      done && "bg-brand-600 text-white",
                      active && "bg-white text-brand-600 ring-brand-100 shadow-md",
                      !done && !active && "bg-slate-100 text-slate-400",
                    )}
                  >
                    {done ? (
                      <Check className="h-4 w-4" />
                    ) : active ? (
                      <LoaderCircle className="h-4 w-4 animate-spin" />
                    ) : (
                      <span className="text-xs font-semibold">{i + 1}</span>
                    )}
                  </span>
                  <div className="pt-1">
                    <div
                      className={clsx(
                        "text-sm font-medium transition-colors",
                        active ? "text-slate-900" : done ? "text-slate-700" : "text-slate-400",
                      )}
                    >
                      {s.label}
                    </div>
                    {active && s.id === "ocr" && (
                      <div className="mt-0.5 text-xs text-slate-500">Every tag on the P&ID is read from left to right. This is the longest step on a scanned drawing.</div>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>

          <div className="mt-8 min-h-[64px] rounded-2xl bg-white p-4 ring-1 ring-slate-200">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-brand-600">Did you know</div>
            <AnimatePresence mode="wait">
              <motion.p
                key={tip}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                className="mt-1 text-sm text-slate-600"
              >
                {TIPS[tip]}
              </motion.p>
            </AnimatePresence>
          </div>
        </div>
      </main>
    </div>
  );
}
