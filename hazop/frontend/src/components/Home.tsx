"use client";

import {
  FileSpreadsheet,
  FileText,
  Clock,
  Gauge,
  Layers,
  ListChecks,
  LogOut,
  RotateCcw,
  ScanText,
  ShieldCheck,
  TriangleAlert,
  Waypoints,
} from "lucide-react";
import { motion } from "motion/react";
import type { JobOptions, ProjectDocuments } from "@/lib/api";
import type { Account, Health } from "@/lib/types";
import SignupPanel from "./SignupPanel";
import UploadPanel from "./UploadPanel";
import { Logo } from "./ui";

const STEPS = [
  {
    icon: ScanText,
    title: "Read the drawing",
    desc: "PDF text layer or tiled OCR (Optical Character Recognition) picks up every tag, line number, valve code and note — including rotated text.",
  },
  { icon: Layers, title: "Understand the P&ID", desc: "ISA 5.1 instruments, API RP 14C equipment, line designations and piping specs are decoded." },
  {
    icon: Waypoints,
    title: "Evaluate risk scenarios",
    desc: "Evaluate risk scenarios against each guide-word deviation for causes, consequences and the safeguards shown on the drawing.",
  },
  { icon: Gauge, title: "Rank risk & recommend", desc: "5×5 or 6×6 risk matrix (C × L) with specific, actionable recommendations — ready for the HAZOP team to review." },
];

const OUTPUTS = [
  { icon: FileText, title: "Word worksheet", desc: "Your company template, landscape, with risk colours" },
  { icon: FileSpreadsheet, title: "Excel workbook", desc: "Worksheet, recommendations, risk matrix & extracted data" },
];

export default function Home({
  health,
  backendDown,
  onRetryHealth,
  onStart,
  submitting,
  lastJob,
  onOpenLast,
  account,
  onSignOut,
}: {
  health: Health | null;
  backendDown: boolean;
  onRetryHealth: () => void;
  onStart: (files: File[], docs: ProjectDocuments, opts: JobOptions) => void;
  submitting: boolean;
  lastJob: string | null;
  onOpenLast: () => void;
  account: Account | null;
  onSignOut: () => void;
}) {
  const needsSignup = !!health?.signup_required && !account;
  return (
    <>
      {/* Hero */}
      <section className="relative overflow-hidden bg-ink-950 text-white">
        <div className="bg-grid-dark absolute inset-0 [mask-image:radial-gradient(ellipse_at_top,black_30%,transparent_75%)]" />
        <div className="absolute -left-40 -top-40 h-[480px] w-[480px] rounded-full bg-brand-600/30 blur-[120px]" />
        <div className="absolute -right-32 top-20 h-[380px] w-[380px] rounded-full bg-cyan-500/20 blur-[120px]" />
        <div className="absolute bottom-0 left-1/3 h-[260px] w-[420px] rounded-full bg-amber-400/10 blur-[110px]" />

        <header className="relative mx-auto flex max-w-7xl items-center justify-between px-5 py-5 sm:px-8">
          <Logo light />
          <div className="flex items-center gap-3">
            {lastJob && (
              <button
                onClick={onOpenLast}
                className="hidden items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium text-slate-300 ring-1 ring-white/15 transition hover:bg-white/10 hover:text-white sm:inline-flex"
              >
                <Clock className="h-3.5 w-3.5" /> Open last worksheet
              </button>
            )}
            {account && (
              <div className="inline-flex items-center gap-2 rounded-full py-1 pl-1 pr-1.5 text-xs text-slate-300 ring-1 ring-white/15">
                <span className="grid h-6 w-6 place-items-center rounded-full bg-gradient-to-br from-brand-500 to-cyan-500 text-[10px] font-semibold text-white">
                  {(account.first_name[0] ?? "") + (account.last_name[0] ?? "")}
                </span>
                <span className="hidden max-w-[140px] truncate font-medium text-white sm:block" title={account.email}>
                  {account.first_name}
                </span>
                <button
                  onClick={onSignOut}
                  title="Sign out"
                  aria-label="Sign out"
                  className="grid h-6 w-6 place-items-center rounded-full text-slate-400 transition hover:bg-white/10 hover:text-white"
                >
                  <LogOut className="h-3.5 w-3.5" />
                </button>
              </div>
            )}
            <span
              className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium ring-1 ${
                backendDown
                  ? "bg-rose-500/10 text-rose-300 ring-rose-400/30"
                  : health
                    ? "bg-emerald-500/10 text-emerald-300 ring-emerald-400/30"
                    : "bg-white/5 text-slate-300 ring-white/15"
              }`}
            >
              <span className="relative flex h-2 w-2">
                {!backendDown && health && (
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
                )}
                <span
                  className={`relative inline-flex h-2 w-2 rounded-full ${backendDown ? "bg-rose-400" : health ? "bg-emerald-400" : "bg-slate-400"}`}
                />
              </span>
              {backendDown ? "Engine offline" : health ? "Engine online" : "Connecting..."}
            </span>
          </div>
        </header>

        <div className="relative mx-auto grid max-w-7xl gap-10 px-5 pb-16 pt-6 sm:px-8 lg:grid-cols-[1.1fr_1fr] lg:gap-14 lg:pb-24 lg:pt-12">
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="flex flex-col justify-center"
          >
            <div className="mb-5 inline-flex w-fit items-center gap-2 rounded-full bg-white/5 px-3 py-1 text-xs font-medium text-slate-300 ring-1 ring-white/10">
              <ShieldCheck className="h-3.5 w-3.5 text-cyan-300" />
              IEC 61882 HAZOP &middot; ISA 5.1 &middot; API RP 14C
            </div>
            <h1 className="text-4xl font-semibold leading-[1.08] tracking-tight sm:text-5xl lg:text-[56px]">
              From P&amp;ID to <span className="text-gradient">HAZOP worksheet</span> in minutes.
            </h1>
            <p className="mt-5 max-w-xl text-base leading-relaxed text-slate-300 sm:text-lg">
              Upload a drawing with your piping specification and risk matrix. HAZOP Studio extracts equipment, instruments,
              lines and valves, then drafts nodes, deviations, safeguards, risk rankings and recommendations — in a table
              you can review, edit and export.
            </p>

            <div className="mt-8 grid max-w-xl grid-cols-3 gap-3">
              {[
                { k: "10+", v: "guide-word deviations per node" },
                { k: "5×5 / 6×6", v: "risk matrix from your project, colour coded" },
                { k: "2", v: "export formats: Word template and Excel" },
              ].map((s) => (
                <div key={s.k} className="rounded-2xl bg-white/[0.04] p-3.5 ring-1 ring-white/10 backdrop-blur">
                  <div className="text-2xl font-semibold text-white">{s.k}</div>
                  <div className="mt-1 text-[11px] leading-snug text-slate-400">{s.v}</div>
                </div>
              ))}
            </div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.55, delay: 0.1 }}
            className="text-slate-900"
          >
            {backendDown && (
              <div className="mb-3 flex items-start gap-3 rounded-2xl bg-rose-50 p-4 text-sm text-rose-800 ring-1 ring-rose-200">
                <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />
                <div className="flex-1">
                  <div className="font-semibold">The analysis engine is not reachable.</div>
                  <div className="mt-0.5 text-xs text-rose-700">
                    Start it with <code className="rounded bg-rose-100 px-1">start.bat</code> (or{" "}
                    <code className="rounded bg-rose-100 px-1">uvicorn app.main:app --port 8000</code> in{" "}
                    <code className="rounded bg-rose-100 px-1">backend</code>), then retry.
                  </div>
                </div>
                <button
                  onClick={onRetryHealth}
                  className="inline-flex items-center gap-1 rounded-lg bg-white px-2.5 py-1.5 text-xs font-medium text-rose-700 ring-1 ring-rose-200 hover:bg-rose-100"
                >
                  <RotateCcw className="h-3.5 w-3.5" /> Retry
                </button>
              </div>
            )}
            {needsSignup ? (
              <SignupPanel verifyEmail={!!health?.signup_verify} />
            ) : (
              <UploadPanel health={health} backendDown={backendDown} submitting={submitting} onStart={onStart} />
            )}
          </motion.div>
        </div>
      </section>

      {/* How it works */}
      <section className="mx-auto w-full max-w-7xl px-5 py-16 sm:px-8 lg:py-20">
        <div className="mx-auto max-w-2xl text-center">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-brand-600">How it works</div>
          <h2 className="mt-2 text-3xl font-semibold tracking-tight text-slate-900">A HAZOP scribe that never gets tired</h2>
          <p className="mt-3 text-slate-500">
            Every row is traceable to what is on the drawing, so your team spends the session on judgement — not typing.
          </p>
        </div>
        <div className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((s, i) => (
            <motion.div
              key={s.title}
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ delay: i * 0.08 }}
              className="group relative rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition hover:-translate-y-1 hover:shadow-lg"
            >
              <div className="mb-4 flex items-center justify-between">
                <div className="grid h-11 w-11 place-items-center rounded-xl bg-gradient-to-br from-brand-50 to-cyan-50 text-brand-600 ring-1 ring-brand-100">
                  <s.icon className="h-5 w-5" />
                </div>
                <span className="font-mono text-xs text-slate-300">0{i + 1}</span>
              </div>
              <h3 className="font-semibold text-slate-900">{s.title}</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-slate-500">{s.desc}</p>
            </motion.div>
          ))}
        </div>

        <div className="mt-14 grid items-center gap-8 rounded-3xl border border-slate-200 bg-gradient-to-br from-white to-brand-50/40 p-8 lg:grid-cols-[1fr_1.4fr]">
          <div>
            <div className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-brand-600">
              <ListChecks className="h-4 w-4" /> Deliverables
            </div>
            <h3 className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">Review on screen, download in one click</h3>
            <p className="mt-2 text-sm leading-relaxed text-slate-500">
              Adjust consequence and likelihood rankings in the browser — risk colours and exports update instantly.
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {OUTPUTS.map((o) => (
              <div key={o.title} className="rounded-2xl bg-white p-4 ring-1 ring-slate-200">
                <o.icon className="h-5 w-5 text-brand-600" />
                <div className="mt-3 text-sm font-semibold text-slate-900">{o.title}</div>
                <div className="mt-0.5 text-xs leading-snug text-slate-500">{o.desc}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <footer className="mt-auto border-t border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-5 py-6 text-xs text-slate-500 sm:px-8">
          <Logo />
          <p>
            Generated worksheets are a starting point to support a facilitated HAZOP team review, not a substitute for the final
            HAZOP report.
          </p>
        </div>
      </footer>
    </>
  );
}
