"use client";

import clsx from "clsx";
import {
  ArrowRight,
  ChevronDown,
  CloudUpload,
  Cpu,
  FileText,
  Image as ImageIcon,
  LoaderCircle,
  Sparkles,
  TriangleAlert,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import type { JobOptions } from "@/lib/api";
import type { Health, StudyInfo } from "@/lib/types";
import { Button, Card } from "./ui";

const ACCEPT = [".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"];

const STUDY_FIELDS: { key: keyof StudyInfo; label: string; placeholder: string; wide?: boolean }[] = [
  { key: "project", label: "Project", placeholder: "e.g. Gas Lift Expansion" },
  { key: "client", label: "Client", placeholder: "e.g. Chevron" },
  { key: "facility", label: "Facility / Unit", placeholder: "Auto-detected from the drawing", wide: true },
  { key: "drawing", label: "Drawing no.", placeholder: "Defaults to file name" },
  { key: "revision", label: "Revision", placeholder: "e.g. Rev B" },
  { key: "date", label: "Study date", placeholder: "" },
  { key: "team", label: "HAZOP team", placeholder: "Chair, scribe, process, instrument..." },
];

function formatSize(bytes: number) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function UploadPanel({
  health,
  backendDown,
  submitting,
  onStart,
}: {
  health: Health | null;
  backendDown: boolean;
  submitting: boolean;
  onStart: (file: File | null, opts: JobOptions) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showStudy, setShowStudy] = useState(false);
  const [study, setStudy] = useState<StudyInfo>({});
  const [mode, setMode] = useState<"rules" | "ai">("rules");
  const [provider, setProvider] = useState<string>("");
  const inputRef = useRef<HTMLInputElement>(null);

  const providers = useMemo(() => health?.providers ?? [], [health]);
  const maxMb = health?.max_upload_mb ?? 25;
  const aiAvailable = providers.length > 0;
  const activeProvider = provider || providers[0]?.id || "";

  const preview = useMemo(() => (file?.type.startsWith("image/") ? URL.createObjectURL(file) : null), [file]);
  useEffect(() => () => void (preview && URL.revokeObjectURL(preview)), [preview]);

  const pick = (f: File | undefined | null) => {
    if (!f) return;
    const ext = "." + (f.name.split(".").pop() ?? "").toLowerCase();
    if (!ACCEPT.includes(ext)) {
      setError(`"${f.name}" is not supported. Upload a PDF or an image (PNG, JPG, TIFF).`);
      return;
    }
    if (f.size > maxMb * 1024 * 1024) {
      setError(`File is ${formatSize(f.size)}. The limit is ${maxMb} MB.`);
      return;
    }
    setError(null);
    setFile(f);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    pick(e.dataTransfer.files?.[0]);
  };

  const options = (): JobOptions => ({
    mode,
    provider: mode === "ai" ? activeProvider : undefined,
    study: Object.fromEntries(Object.entries(study).filter(([, v]) => v && String(v).trim())) as StudyInfo,
  });

  return (
    <Card className="relative overflow-hidden p-5 sm:p-6">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-900">Start a new study</h2>
          <p className="text-xs text-slate-500">Upload one P&amp;ID sheet. PDF works best.</p>
        </div>
        <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-medium text-emerald-700 ring-1 ring-emerald-200">
          ~1-2 min per sheet
        </span>
      </div>

      {/* Dropzone */}
      <div
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={clsx(
          "group relative flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-8 text-center transition-all duration-200 outline-none",
          dragging
            ? "scale-[1.01] border-brand-500 bg-brand-50"
            : "border-slate-200 bg-slate-50/70 hover:border-brand-400 hover:bg-brand-50/50 focus-visible:border-brand-500",
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT.join(",")}
          className="hidden"
          onChange={(e) => {
            pick(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        <AnimatePresence mode="wait" initial={false}>
          {file ? (
            <motion.div
              key="file"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              className="flex w-full items-center gap-4 text-left"
            >
              <div className="relative h-16 w-20 shrink-0 overflow-hidden rounded-xl bg-white ring-1 ring-slate-200">
                {preview ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={preview} alt="" className="h-full w-full object-cover" />
                ) : (
                  <div className="grid h-full w-full place-items-center bg-gradient-to-br from-rose-50 to-white">
                    <FileText className="h-7 w-7 text-rose-500" />
                  </div>
                )}
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold text-slate-900">{file.name}</div>
                <div className="mt-0.5 flex items-center gap-2 text-xs text-slate-500">
                  {file.type.startsWith("image/") ? <ImageIcon className="h-3.5 w-3.5" /> : <FileText className="h-3.5 w-3.5" />}
                  {formatSize(file.size)} &middot; ready to analyse
                </div>
                <div className="mt-1 text-[11px] text-brand-600 group-hover:underline">Click to choose another file</div>
              </div>
              <button
                type="button"
                aria-label="Remove file"
                onClick={(e) => {
                  e.stopPropagation();
                  setFile(null);
                }}
                className="grid h-8 w-8 place-items-center rounded-lg text-slate-400 transition hover:bg-white hover:text-slate-700"
              >
                <X className="h-4 w-4" />
              </button>
            </motion.div>
          ) : (
            <motion.div key="empty" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}>
              <div className="mx-auto mb-3 grid h-14 w-14 place-items-center rounded-2xl bg-white shadow-sm ring-1 ring-slate-200 transition group-hover:-translate-y-0.5 group-hover:shadow-md">
                <CloudUpload className={clsx("h-6 w-6 transition", dragging ? "text-brand-600" : "text-brand-500")} />
              </div>
              <div className="text-sm font-semibold text-slate-800">
                {dragging ? "Drop your P&ID here" : "Drag & drop your P&ID"}
              </div>
              <div className="mt-1 text-xs text-slate-500">
                or <span className="font-medium text-brand-600">browse files</span> &middot; PDF, PNG, JPG, TIFF up to {maxMb} MB
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {error && (
        <div className="mt-3 flex items-start gap-2 rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-700 ring-1 ring-rose-200">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {error}
        </div>
      )}

      {/* Analysis mode */}
      <div className="mt-5">
        <div className="mb-2 text-xs font-medium text-slate-600">Analysis engine</div>
        <div className="grid grid-cols-2 gap-2">
          {[
            { id: "rules" as const, icon: Cpu, title: "Rule engine", desc: "Offline, deterministic, standards-based", disabled: false },
            {
              id: "ai" as const,
              icon: Sparkles,
              title: "AI-assisted",
              desc: aiAvailable ? "Rule engine + vision LLM review" : "Add an API key in backend/.env",
              disabled: !aiAvailable,
            },
          ].map((m) => (
            <button
              key={m.id}
              type="button"
              disabled={m.disabled}
              onClick={() => setMode(m.id)}
              className={clsx(
                "relative flex items-start gap-2.5 rounded-xl border p-3 text-left transition",
                mode === m.id
                  ? "border-brand-500 bg-brand-50/60 ring-1 ring-brand-500"
                  : "border-slate-200 bg-white hover:border-slate-300",
                m.disabled && "cursor-not-allowed opacity-60",
              )}
            >
              <div
                className={clsx(
                  "grid h-8 w-8 shrink-0 place-items-center rounded-lg",
                  mode === m.id ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-500",
                )}
              >
                <m.icon className="h-4 w-4" />
              </div>
              <div className="min-w-0">
                <div className="text-[13px] font-semibold text-slate-900">{m.title}</div>
                <div className="text-[11px] leading-snug text-slate-500">{m.desc}</div>
              </div>
            </button>
          ))}
        </div>
        {mode === "ai" && providers.length > 1 && (
          <select
            value={activeProvider}
            onChange={(e) => setProvider(e.target.value)}
            className="mt-2 h-9 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700 outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
          >
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label} ({p.model})
              </option>
            ))}
          </select>
        )}
      </div>

      {/* Study details */}
      <div className="mt-4 rounded-xl border border-slate-200">
        <button
          type="button"
          onClick={() => setShowStudy((s) => !s)}
          className="flex w-full items-center justify-between px-3.5 py-2.5 text-left"
        >
          <span className="text-xs font-medium text-slate-700">
            Study details <span className="font-normal text-slate-400">&middot; optional, printed on the worksheet</span>
          </span>
          <ChevronDown className={clsx("h-4 w-4 text-slate-400 transition", showStudy && "rotate-180")} />
        </button>
        <AnimatePresence initial={false}>
          {showStudy && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden"
            >
              <div className="grid grid-cols-2 gap-2.5 border-t border-slate-100 p-3.5">
                {STUDY_FIELDS.map((f) => (
                  <label key={f.key} className={clsx("block", f.wide && "col-span-2")}>
                    <span className="mb-1 block text-[11px] font-medium text-slate-500">{f.label}</span>
                    <input
                      type={f.key === "date" ? "date" : "text"}
                      value={study[f.key] ?? ""}
                      placeholder={f.placeholder}
                      onChange={(e) => setStudy((s) => ({ ...s, [f.key]: e.target.value }))}
                      className="h-9 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
                    />
                  </label>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <Button
        size="lg"
        className="mt-5 w-full"
        disabled={!file || submitting || backendDown}
        onClick={() => onStart(file, options())}
      >
        {submitting ? <LoaderCircle className="h-4 w-4 animate-spin" /> : null}
        Generate HAZOP worksheet
        {!submitting && <ArrowRight className="h-4 w-4" />}
      </Button>

      {health?.samples?.length ? (
        <div className="mt-3 text-center text-xs text-slate-500">
          No drawing handy?{" "}
          <button
            type="button"
            disabled={submitting || backendDown}
            onClick={() => onStart(null, options())}
            className="font-medium text-brand-600 underline-offset-2 hover:underline disabled:opacity-50"
          >
            Try the sample P&amp;ID ({health.samples[0].replace(/\.[^.]+$/, "")})
          </button>
        </div>
      ) : null}
    </Card>
  );
}
