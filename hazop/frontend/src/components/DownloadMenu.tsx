"use client";

import clsx from "clsx";
import { Braces, Check, ChevronDown, Download, FileSpreadsheet, FileText, LoaderCircle, TriangleAlert } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { downloadExport, type ExportFormat } from "@/lib/api";
import type { Extraction, Worksheet } from "@/lib/types";
import { Button } from "./ui";

const ITEMS: { fmt: ExportFormat; icon: typeof FileText; title: string; desc: string; tint: string }[] = [
  { fmt: "docx", icon: FileText, title: "Word worksheet", desc: "Company template · .docx", tint: "bg-blue-50 text-blue-600 ring-blue-100" },
  { fmt: "xlsx", icon: FileSpreadsheet, title: "Excel workbook", desc: "Worksheet + data · .xlsx", tint: "bg-emerald-50 text-emerald-600 ring-emerald-100" },
  { fmt: "json", icon: Braces, title: "JSON data", desc: "For integrations · .json", tint: "bg-slate-100 text-slate-600 ring-slate-200" },
];

export default function DownloadMenu({ worksheet, extraction }: { worksheet: Worksheet; extraction: Extraction }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<ExportFormat | null>(null);
  const [done, setDone] = useState<ExportFormat | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, []);

  const run = async (fmt: ExportFormat) => {
    setBusy(fmt);
    setError(null);
    try {
      await downloadExport(fmt, worksheet, extraction);
      setDone(fmt);
      setTimeout(() => setDone(null), 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div ref={ref} className="relative">
      <Button onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <Download className="h-4 w-4" /> Download
        <ChevronDown className={clsx("h-4 w-4 transition", open && "rotate-180")} />
      </Button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.15 }}
            className="absolute right-0 top-full z-50 mt-2 w-72 origin-top-right rounded-2xl bg-white p-1.5 shadow-2xl ring-1 ring-slate-200"
          >
            {ITEMS.map((it) => (
              <button
                key={it.fmt}
                disabled={!!busy}
                onClick={() => run(it.fmt)}
                className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition hover:bg-slate-50 disabled:opacity-60"
              >
                <span className={clsx("grid h-9 w-9 place-items-center rounded-lg ring-1", it.tint)}>
                  <it.icon className="h-4 w-4" />
                </span>
                <span className="flex-1">
                  <span className="block text-sm font-medium text-slate-900">{it.title}</span>
                  <span className="block text-[11px] text-slate-500">{it.desc}</span>
                </span>
                {busy === it.fmt && <LoaderCircle className="h-4 w-4 animate-spin text-brand-600" />}
                {done === it.fmt && <Check className="h-4 w-4 text-emerald-600" />}
              </button>
            ))}
            {error && (
              <div className="m-1 flex items-start gap-2 rounded-lg bg-rose-50 px-2.5 py-2 text-[11px] text-rose-700">
                <TriangleAlert className="mt-px h-3.5 w-3.5 shrink-0" /> {error}
              </div>
            )}
            <div className="mt-1 border-t border-slate-100 px-3 pb-1 pt-2 text-[11px] text-slate-400">Exports include your C / L edits.</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
