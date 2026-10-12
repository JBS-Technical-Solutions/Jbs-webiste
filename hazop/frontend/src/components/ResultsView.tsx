"use client";

import clsx from "clsx";
import {
  Grid3x3,
  Layers,
  ListChecks,
  Plus,
  RotateCcw,
  ScanSearch,
  Table2,
  TriangleAlert,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useMemo, useState } from "react";
import { bandsOf, DEFAULT_MATRIX, evaluate, RiskMatrixContext } from "@/lib/risk";
import type { Job, RiskCode, Worksheet, WorksheetRow } from "@/lib/types";
import DownloadMenu from "./DownloadMenu";
import PidViewer from "./PidViewer";
import RecommendationsView from "./RecommendationsView";
import RiskMatrixView from "./RiskMatrixView";
import WorksheetView, { type WorksheetFilter } from "./WorksheetView";
import { Button, Logo } from "./ui";

type Tab = "worksheet" | "pid" | "recs" | "matrix";

function allRows(ws: Worksheet) {
  return ws.nodes.flatMap((n) => n.deviations.flatMap((d) => d.rows));
}

export default function ResultsView({ job, onNew }: { job: Job; onNew: () => void }) {
  const result = job.result!;
  const original = result.worksheet;
  const [ws, setWs] = useState<Worksheet>(() => structuredClone(original));
  const [edited, setEdited] = useState(false);
  const [tab, setTab] = useState<Tab>("worksheet");
  const [filter, setFilter] = useState<WorksheetFilter>({ risk: [], search: "", cell: null, node: "all" });
  const [focusTag, setFocusTag] = useState<string | null>(null);
  const [focusRec, setFocusRec] = useState<string | null>(null);
  const [warningsOpen, setWarningsOpen] = useState(true);
  const matrix = ws.risk_matrix ?? DEFAULT_MATRIX;
  const bands = bandsOf(matrix);

  const rows = useMemo(() => allRows(ws), [ws]);
  const dist = useMemo(() => {
    const d: Record<RiskCode, number> = { L: 0, M: 0, H: 0, VH: 0 };
    rows.forEach((r) => (d[r.risk.code] += 1));
    return d;
  }, [rows]);

  const updateRow = (n: number, d: number, r: number, patch: Partial<Pick<WorksheetRow, "c" | "l">>) => {
    setWs((prev) => {
      const next = structuredClone(prev);
      const row = next.nodes[n].deviations[d].rows[r];
      Object.assign(row, patch);
      row.risk = evaluate(row.c, row.l, next.risk_matrix ?? DEFAULT_MATRIX);
      return next;
    });
    setEdited(true);
  };

  const reset = () => {
    setWs(structuredClone(original));
    setEdited(false);
  };

  const gotoTag = (tag: string) => {
    setFocusTag(tag);
    setTab("pid");
  };
  const gotoRec = (id: string) => {
    setFocusRec(id);
    setTab("recs");
  };
  const gotoCell = (c: number, l: number) => {
    setFilter((f) => ({ ...f, cell: { c, l }, risk: [] }));
    setTab("worksheet");
  };

  const study = ws.study;
  const s = result.stats;
  const highCount = dist.H + dist.VH;

  const TABS: { id: Tab; label: string; icon: typeof Table2; count?: number }[] = [
    { id: "worksheet", label: "HAZOP worksheet", icon: Table2, count: rows.length },
    { id: "pid", label: "P&ID & data", icon: ScanSearch, count: s.equipment + s.instruments + s.lines + s.valves + result.extraction.connectors.length },
    { id: "recs", label: "Recommendations", icon: ListChecks, count: Object.keys(ws.recommendations).length },
    { id: "matrix", label: "Risk matrix", icon: Grid3x3 },
  ];

  return (
    <RiskMatrixContext value={matrix}>
    <div className="flex min-h-screen flex-col bg-slate-50">
      {/* Top bar */}
      <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/85 backdrop-blur-md">
        <div className="mx-auto flex max-w-[1600px] items-center gap-4 px-4 py-3 sm:px-6">
          <Logo />
          <div className="hidden h-8 w-px bg-slate-200 md:block" />
          <div className="hidden min-w-0 flex-1 md:block">
            <div className="truncate text-sm font-semibold text-slate-900">{study.facility || job.filename}</div>
            <div className="truncate text-xs text-slate-500">
              {study.drawing || job.filename}
              {study.project ? ` · ${study.project}` : ""}
              {study.client ? ` · ${study.client}` : ""}
            </div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <AnimatePresence>
              {edited && (
                <motion.div initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0 }} className="flex items-center gap-1">
                  <span className="hidden rounded-full bg-amber-50 px-2.5 py-1 text-[11px] font-medium text-amber-700 ring-1 ring-amber-200 sm:inline">
                    Edited
                  </span>
                  <Button variant="ghost" size="sm" onClick={reset} title="Discard your edits">
                    <RotateCcw className="h-3.5 w-3.5" /> Reset
                  </Button>
                </motion.div>
              )}
            </AnimatePresence>
            <Button variant="secondary" size="md" onClick={onNew}>
              <Plus className="h-4 w-4" /> <span className="hidden sm:inline">New analysis</span>
            </Button>
            <DownloadMenu worksheet={ws} extraction={result.extraction} />
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 pb-16 pt-6 sm:px-6">
        {/* Warnings */}
        <AnimatePresence>
          {warningsOpen && job.warnings.length > 0 && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="mb-5 overflow-hidden"
            >
              <div className="flex items-start gap-3 rounded-2xl bg-amber-50 px-4 py-3 text-sm text-amber-900 ring-1 ring-amber-200">
                <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                <ul className="flex-1 space-y-0.5">
                  {job.warnings.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
                <button onClick={() => setWarningsOpen(false)} className="text-amber-600 hover:text-amber-800" aria-label="Dismiss">
                  <X className="h-4 w-4" />
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Title + stats */}
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-xs font-medium text-brand-600">
              <Layers className="h-3.5 w-3.5" /> {study.analysis ?? "Rule-based engine"}
              <span className="text-slate-300">&bull;</span>
              <span className="text-slate-500">
                {result.text_method === "pdf-text" ? "PDF text layer" : "OCR (Optical Character Recognition)"} &middot;{" "}
                {Object.values(result.timings).reduce((a, b) => a + b, 0).toFixed(1)}s
              </span>
            </div>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-900 sm:text-[28px]">
              {study.title || "HAZOP Worksheets"}
            </h1>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-5 xl:grid-cols-6">
          {[
            { label: "Nodes", value: ws.nodes.length },
            { label: "Deviations", value: ws.nodes.reduce((a, n) => a + n.deviations.length, 0) },
            { label: "Causes analysed", value: rows.length },
            { label: "Recommendations", value: Object.keys(ws.recommendations).length },
            { label: "High / Very high", value: highCount, accent: highCount > 0 },
          ].map((c, i) => (
            <motion.div
              key={c.label}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
              className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
            >
              <div className="text-xs font-medium text-slate-500">{c.label}</div>
              <div className={clsx("mt-1 text-[28px] font-semibold leading-none tabular-nums", c.accent ? "text-orange-600" : "text-slate-900")}>
                {c.value}
              </div>
            </motion.div>
          ))}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.25 }}
            className="col-span-2 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm md:col-span-5 xl:col-span-1"
          >
            <div className="text-xs font-medium text-slate-500">Risk profile</div>
            <div className="mt-2.5 flex h-3 overflow-hidden rounded-full bg-slate-100">
              {bands.map((b) =>
                dist[b.code] ? (
                  <motion.div
                    key={b.code}
                    initial={{ width: 0 }}
                    animate={{ width: `${(dist[b.code] / Math.max(rows.length, 1)) * 100}%` }}
                    transition={{ duration: 0.6 }}
                    style={{ background: b.color, boxShadow: `inset 0 0 0 1px ${b.ring}` }}
                    title={`${b.name}: ${dist[b.code]}`}
                  />
                ) : null,
              )}
            </div>
            <div className="mt-2 flex justify-between text-[11px] text-slate-500">
              {bands.map((b) => (
                <button
                  key={b.code}
                  onClick={() => {
                    setFilter((f) => ({ ...f, risk: [b.code], cell: null }));
                    setTab("worksheet");
                  }}
                  className="flex items-center gap-1 hover:text-slate-900"
                >
                  <span className="h-2 w-2 rounded-full" style={{ background: b.color, boxShadow: `0 0 0 1px ${b.ring}` }} />
                  {b.code} {dist[b.code]}
                </button>
              ))}
            </div>
          </motion.div>
        </div>

        {/* Tabs */}
        <div className="sticky top-[61px] z-30 -mx-4 mt-7 bg-slate-50/90 px-4 pb-3 pt-1 backdrop-blur sm:-mx-6 sm:px-6">
          <div className="flex gap-1 overflow-x-auto rounded-2xl bg-white p-1 shadow-sm ring-1 ring-slate-200 [scrollbar-width:none]">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={clsx(
                  "relative flex shrink-0 items-center gap-2 rounded-xl px-3 py-2 text-sm font-medium transition-colors lg:px-4",
                  tab === t.id ? "text-white" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900",
                )}
              >
                {tab === t.id && (
                  <motion.span
                    layoutId="tab-pill"
                    className="absolute inset-0 rounded-xl bg-gradient-to-b from-brand-500 to-brand-600 shadow-md shadow-brand-600/25"
                    transition={{ type: "spring", bounce: 0.15, duration: 0.45 }}
                  />
                )}
                <t.icon className="relative h-4 w-4" />
                <span className="relative">{t.label}</span>
                {t.count !== undefined && (
                  <span
                    className={clsx(
                      "relative rounded-full px-1.5 py-px text-[10px] font-semibold tabular-nums",
                      tab === t.id ? "bg-white/20 text-white" : "bg-slate-100 text-slate-500",
                    )}
                  >
                    {t.count}
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>

        <AnimatePresence mode="wait">
          <motion.div
            key={tab}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.2 }}
            className="mt-2"
          >
            {tab === "worksheet" && (
              <WorksheetView ws={ws} filter={filter} setFilter={setFilter} onUpdate={updateRow} onTag={gotoTag} onRec={gotoRec} />
            )}
            {tab === "pid" && (
              <PidViewer image={result.image} extraction={result.extraction} focusTag={focusTag} onFocusHandled={() => setFocusTag(null)} />
            )}
            {tab === "recs" && <RecommendationsView ws={ws} focus={focusRec} />}
            {tab === "matrix" && <RiskMatrixView rows={rows} onCell={gotoCell} />}
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
    </RiskMatrixContext>
  );
}
