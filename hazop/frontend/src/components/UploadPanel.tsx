"use client";

import clsx from "clsx";
import {
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  CloudUpload,
  Cpu,
  FileSpreadsheet,
  FileText,
  Grid3x3,
  Image as ImageIcon,
  ListTree,
  LoaderCircle,
  Paperclip,
  Plus,
  Sparkles,
  TriangleAlert,
  Wand2,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useRef, useState, type DragEvent, type ReactNode } from "react";
import { checkDocument, type JobOptions, type ProjectDocuments } from "@/lib/api";
import type { DocumentKind, Health, NodeMode, StudyInfo } from "@/lib/types";
import { Button, Card } from "./ui";

const ACCEPT = [".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"];
const OFFICE = [".xlsx", ".xlsm", ".docx"];
const DOC_ACCEPT = [...OFFICE, ...ACCEPT];
const OPTIONAL_ACCEPT = [...DOC_ACCEPT, ".txt"];

const STUDY_FIELDS: { key: keyof StudyInfo; label: string; placeholder: string; wide?: boolean }[] = [
  { key: "project", label: "Project", placeholder: "e.g. Compressor Station" },
  { key: "client", label: "Company", placeholder: "e.g. JBS Technical Solutions" },
  { key: "facility", label: "Facility / Unit", placeholder: "e.g. Compressor train-3", wide: true },
  { key: "drawing", label: "Drawing no.", placeholder: "Defaults to file name" },
  { key: "revision", label: "Revision", placeholder: "e.g. Rev B" },
  { key: "date", label: "Study date", placeholder: "" },
  { key: "team", label: "HAZOP team", placeholder: "Chair, scribe, process, instrument..." },
];

const NODE_MODES: { id: NodeMode; icon: typeof Wand2; title: string; desc: string }[] = [
  { id: "auto", icon: Wand2, title: "Automated", desc: "Uses Node 1, Node 2… if marked on the sheet, otherwise finds them" },
  { id: "user", icon: ListTree, title: "User-defined", desc: "Review and define the nodes yourself" },
];

function formatSize(bytes: number) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

const extOf = (name: string) => "." + (name.split(".").pop() ?? "").toLowerCase();

type DocState = { file: File; status: "checking" | "ok" | "error"; message: string };

function DocSlot({
  title,
  icon,
  state,
  onPick,
  onClear,
  accept = DOC_ACCEPT,
  hint = "Excel, Word, PDF or image (JPG, PNG)",
}: {
  title: string;
  icon: ReactNode;
  state: DocState | null;
  onPick: (f: File) => void;
  onClear: () => void;
  accept?: string[];
  hint?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <div
      className={clsx(
        "rounded-xl border p-3 transition",
        state?.status === "ok" && "border-emerald-200 bg-emerald-50/40",
        state?.status === "error" && "border-rose-200 bg-rose-50/40",
        (!state || state.status === "checking") && "border-slate-200 bg-white",
      )}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept.join(",")}
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onPick(f);
          e.target.value = "";
        }}
      />
      <div className="flex items-center gap-2.5">
        <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-slate-100 text-slate-500">{icon}</div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 text-[13px] font-semibold text-slate-900">
            {title}
            <span className="rounded bg-rose-50 px-1 py-px text-[10px] font-medium text-rose-600 ring-1 ring-rose-200">Required</span>
          </div>
          {state ? (
            <div className="flex min-w-0 items-center gap-1 text-[11px] text-slate-500">
              {state.status === "checking" && <LoaderCircle className="h-3 w-3 shrink-0 animate-spin text-brand-600" />}
              {state.status === "ok" && <CheckCircle2 className="h-3 w-3 shrink-0 text-emerald-600" />}
              {state.status === "error" && <TriangleAlert className="h-3 w-3 shrink-0 text-rose-600" />}
              <span className="truncate font-medium text-slate-700">{state.file.name}</span>
              {state.status !== "error" && <span className="min-w-0 truncate">&middot; {state.message}</span>}
            </div>
          ) : (
            <div className="text-[11px] text-slate-500">{hint}</div>
          )}
        </div>
        {state ? (
          <button
            type="button"
            aria-label={`Remove ${title}`}
            onClick={onClear}
            className="grid h-7 w-7 shrink-0 place-items-center rounded-lg text-slate-400 transition hover:bg-white hover:text-slate-700"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        ) : null}
        <Button variant="secondary" size="sm" className="shrink-0" onClick={() => inputRef.current?.click()}>
          {state ? "Replace" : "Choose file"}
        </Button>
      </div>
      {state?.status === "error" && <div className="mt-2 text-[11px] leading-snug text-rose-700">{state.message}</div>}
    </div>
  );
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
  onStart: (files: File[], docs: ProjectDocuments, opts: JobOptions) => void;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showStudy, setShowStudy] = useState(false);
  const [study, setStudy] = useState<StudyInfo>({});
  const [mode, setMode] = useState<"rules" | "ai">("rules");
  const [nodeMode, setNodeMode] = useState<NodeMode>("auto");
  const [provider, setProvider] = useState<string>("");
  const [docs, setDocs] = useState<Record<DocumentKind, DocState | null>>({
    "piping-spec": null,
    "risk-matrix": null,
    pfd: null,
  });
  const [optional, setOptional] = useState<File[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const optionalRef = useRef<HTMLInputElement>(null);

  const providers = useMemo(() => health?.providers ?? [], [health]);
  const maxMb = health?.max_upload_mb ?? 25;
  const maxSheets = health?.max_pid_pages ?? 500;
  const maxOptional = health?.max_optional_docs ?? 5;
  const aiAvailable = providers.length > 0;
  const activeProvider = provider || providers[0]?.id || "";
  const modeChosen = useRef(false);
  useEffect(() => {
    if (aiAvailable && !modeChosen.current) setMode("ai");
  }, [aiAvailable]);

  const tooBig = (f: File) => (f.size > maxMb * 1024 * 1024 ? `"${f.name}" is ${formatSize(f.size)}. The limit is ${maxMb} MB.` : null);

  const pickMany = (list: FileList | File[] | null | undefined) => {
    const incoming = Array.from(list ?? []);
    if (!incoming.length) return;
    const next = [...files];
    for (const f of incoming) {
      if (!ACCEPT.includes(extOf(f.name))) {
        setError(`"${f.name}" is not supported. Upload a PDF or an image (PNG, JPG, TIFF).`);
        return;
      }
      const big = tooBig(f);
      if (big) return setError(big);
      if (next.length >= maxSheets) {
        setError(`Select at most ${maxSheets} P&ID files. Pages inside a PDF are read on top of that, up to ${maxSheets} sheets.`);
        return;
      }
      if (!next.some((x) => x.name === f.name && x.size === f.size)) next.push(f);
    }
    setError(null);
    setFiles(next);
  };

  const pickDoc = async (kind: DocumentKind, f: File) => {
    const fail = (message: string) => setDocs((d) => ({ ...d, [kind]: { file: f, status: "error", message } }));
    const allowed = kind === "pfd" ? ACCEPT : DOC_ACCEPT;
    if (!allowed.includes(extOf(f.name))) {
      return fail(kind === "pfd"
        ? "Upload the PFD as a PDF or an image (PNG, JPG, TIFF)."
        : "Upload an Excel or Word file, a PDF or an image (JPG, PNG).");
    }
    const big = tooBig(f);
    if (big) return fail(big);
    const message = kind === "pfd" ? "Checking the drawing…" : OFFICE.includes(extOf(f.name)) ? "Checking…" : "Reading the table (OCR)…";
    setDocs((d) => ({ ...d, [kind]: { file: f, status: "checking", message } }));
    try {
      const res = await checkDocument(kind, f);
      setDocs((d) => (d[kind]?.file === f ? { ...d, [kind]: { file: f, status: "ok", message: res.summary } } : d));
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setDocs((d) => (d[kind]?.file === f ? { ...d, [kind]: { file: f, status: "error", message } } : d));
    }
  };

  const addOptional = (files: FileList | null) => {
    if (!files) return;
    const next = [...optional];
    for (const f of Array.from(files)) {
      if (!OPTIONAL_ACCEPT.includes(extOf(f.name))) return setError(`"${f.name}" is not a supported document type.`);
      const big = tooBig(f);
      if (big) return setError(big);
      if (next.length >= maxOptional) return setError(`Attach at most ${maxOptional} optional documents.`);
      if (!next.some((x) => x.name === f.name && x.size === f.size)) next.push(f);
    }
    setError(null);
    setOptional(next);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    pickMany(e.dataTransfer.files);
  };

  const spec = docs["piping-spec"];
  const matrix = docs["risk-matrix"];
  const pfd = docs.pfd;
  const missing = [
    files.length === 0 && "P&ID",
    spec?.status !== "ok" && "piping specification",
    matrix?.status !== "ok" && "risk matrix",
    pfd?.status !== "ok" && "PFD",
  ].filter(Boolean) as string[];
  const ready = missing.length === 0;

  const start = () => {
    if (!files.length || !spec || !matrix || !pfd || !ready) return;
    onStart(
      files,
      { pipingSpec: spec.file, riskMatrix: matrix.file, pfd: pfd.file, optional },
      {
        mode,
        nodeMode,
        provider: mode === "ai" ? activeProvider : undefined,
        study: Object.fromEntries(Object.entries(study).filter(([, v]) => v && String(v).trim())) as StudyInfo,
      },
    );
  };

  return (
    <Card className="relative overflow-hidden p-5 sm:p-6">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-900">Start a new study</h2>
          <p className="text-xs text-slate-500">Upload up to {maxSheets} P&amp;IDs in one run, plus the piping specification, risk matrix and PFD.</p>
        </div>
        <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-medium text-emerald-700 ring-1 ring-emerald-200">
          Up to {maxSheets} P&amp;IDs
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
          "group relative flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-6 text-center transition-all duration-200 outline-none",
          dragging
            ? "scale-[1.01] border-brand-500 bg-brand-50"
            : "border-slate-200 bg-slate-50/70 hover:border-brand-400 hover:bg-brand-50/50 focus-visible:border-brand-500",
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT.join(",")}
          multiple
          className="hidden"
          onChange={(e) => {
            pickMany(e.target.files);
            e.target.value = "";
          }}
        />
        <AnimatePresence mode="wait" initial={false}>
          {files.length > 0 ? (
            <motion.div
              key="file"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              className="w-full text-left"
              onClick={(e) => e.stopPropagation()}
              onKeyDown={(e) => e.stopPropagation()}
            >
              <div className="mb-2 flex items-center justify-between gap-3">
                <div className="text-sm font-semibold text-slate-900">
                  {files.length} P&amp;ID{files.length === 1 ? "" : "s"} selected
                </div>
                <button
                  type="button"
                  onClick={() => inputRef.current?.click()}
                  className="text-[11px] font-medium text-brand-600 hover:underline"
                >
                  Add more
                </button>
              </div>
              <ul className="max-h-44 space-y-1 overflow-auto">
                {files.map((f, index) => (
                  <li
                    key={`${f.name}-${f.size}-${index}`}
                    className="flex items-center gap-2 rounded-lg bg-white px-2 py-1.5 ring-1 ring-slate-200"
                  >
                    {f.type.startsWith("image/") ? (
                      <ImageIcon className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                    ) : (
                      <FileText className="h-3.5 w-3.5 shrink-0 text-rose-500" />
                    )}
                    <span className="min-w-0 flex-1 truncate text-xs font-medium text-slate-800" title={f.name}>
                      {f.name}
                    </span>
                    <span className="shrink-0 text-[11px] tabular-nums text-slate-400">{formatSize(f.size)}</span>
                    <button
                      type="button"
                      aria-label={`Remove ${f.name}`}
                      onClick={() => setFiles((current) => current.filter((_, i) => i !== index))}
                      className="grid h-6 w-6 shrink-0 place-items-center rounded-md text-slate-400 transition hover:bg-rose-50 hover:text-rose-600"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            </motion.div>
          ) : (
            <motion.div key="empty" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}>
              <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-white shadow-sm ring-1 ring-slate-200 transition group-hover:-translate-y-0.5 group-hover:shadow-md">
                <CloudUpload className={clsx("h-6 w-6 transition", dragging ? "text-brand-600" : "text-brand-500")} />
              </div>
              <div className="text-sm font-semibold text-slate-800">
                {dragging ? "Drop your P&IDs here" : "Drag & drop one or many P&IDs"}
              </div>
              <div className="mt-1 text-xs text-slate-500">
                or <span className="font-medium text-brand-600">browse files</span> &middot; up to {maxSheets} drawings &middot; PDF, PNG, JPG, TIFF up to {maxMb} MB each
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Project documents */}
      <div className="mt-4 space-y-2">
        <DocSlot
          title="Piping specification"
          icon={<FileSpreadsheet className="h-4 w-4" />}
          state={spec}
          onPick={(f) => pickDoc("piping-spec", f)}
          onClear={() => setDocs((d) => ({ ...d, "piping-spec": null }))}
        />
        <DocSlot
          title="Risk matrix (5×5 or 6×6)"
          icon={<Grid3x3 className="h-4 w-4" />}
          state={matrix}
          onPick={(f) => pickDoc("risk-matrix", f)}
          onClear={() => setDocs((d) => ({ ...d, "risk-matrix": null }))}
        />
        <DocSlot
          title="PFD"
          icon={<FileText className="h-4 w-4" />}
          state={pfd}
          accept={ACCEPT}
          hint="PDF or image (PNG, JPG, TIFF)"
          onPick={(f) => pickDoc("pfd", f)}
          onClear={() => setDocs((d) => ({ ...d, pfd: null }))}
        />

        <div className="rounded-xl border border-dashed border-slate-200 p-3">
          <input
            ref={optionalRef}
            type="file"
            multiple
            accept={OPTIONAL_ACCEPT.join(",")}
            className="hidden"
            onChange={(e) => {
              addOptional(e.target.files);
              e.target.value = "";
            }}
          />
          <div className="flex items-center gap-2.5">
            <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-slate-100 text-slate-500">
              <Paperclip className="h-4 w-4" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5 text-[13px] font-semibold text-slate-900">
                Other documents
                <span className="rounded bg-slate-100 px-1 py-px text-[10px] font-medium text-slate-500 ring-1 ring-slate-200">Optional</span>
              </div>
              <div className="text-[11px] text-slate-500">Cause &amp; effect, datasheets… up to {maxOptional}</div>
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="shrink-0"
              disabled={optional.length >= maxOptional}
              onClick={() => optionalRef.current?.click()}
            >
              <Plus className="h-3.5 w-3.5" /> Add
            </Button>
          </div>
          {optional.length > 0 && (
            <div className="mt-2.5 flex flex-wrap gap-1.5">
              {optional.map((f, i) => (
                <span
                  key={`${f.name}-${f.size}`}
                  className="inline-flex max-w-full items-center gap-1 rounded-lg bg-slate-100 py-1 pl-2 pr-1 text-[11px] font-medium text-slate-700"
                >
                  <span className="truncate">{f.name}</span>
                  <button
                    type="button"
                    aria-label={`Remove ${f.name}`}
                    onClick={() => setOptional((o) => o.filter((_, j) => j !== i))}
                    className="grid h-4 w-4 shrink-0 place-items-center rounded text-slate-400 hover:bg-white hover:text-slate-700"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {error && (
        <div className="mt-3 flex items-start gap-2 rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-700 ring-1 ring-rose-200">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {error}
        </div>
      )}

      {/* HAZOP nodes */}
      <div className="mt-5">
        <div className="mb-2 text-xs font-medium text-slate-600">HAZOP nodes</div>
        <div className="grid grid-cols-2 gap-2">
          {NODE_MODES.map((m) => (
            <button
              key={m.id}
              type="button"
              onClick={() => setNodeMode(m.id)}
              className={clsx(
                "relative flex items-start gap-2.5 rounded-xl border p-3 text-left transition",
                nodeMode === m.id ? "border-brand-500 bg-brand-50/60 ring-1 ring-brand-500" : "border-slate-200 bg-white hover:border-slate-300",
              )}
            >
              <div
                className={clsx(
                  "grid h-8 w-8 shrink-0 place-items-center rounded-lg",
                  nodeMode === m.id ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-500",
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
      </div>

      {/* Analysis mode */}
      <div className="mt-4">
        <div className="mb-2 text-xs font-medium text-slate-600">Analysis engine</div>
        <div className="grid grid-cols-2 gap-2">
          {[
            { id: "rules" as const, icon: Cpu, title: "Rule engine", desc: "Offline, deterministic, standards-based", disabled: false },
            {
              id: "ai" as const,
              icon: Sparkles,
              title: "AI-assisted",
              desc: aiAvailable ? "Reading steps first, then Gemini checks causes and safeguards" : "Add an API key in backend/.env",
              disabled: !aiAvailable,
            },
          ].map((m) => (
            <button
              key={m.id}
              type="button"
              disabled={m.disabled}
              onClick={() => {
                modeChosen.current = true;
                setMode(m.id);
              }}
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

      <Button size="lg" className="mt-5 w-full" disabled={!ready || submitting || backendDown} onClick={start}>
        {submitting ? <LoaderCircle className="h-4 w-4 animate-spin" /> : null}
        {nodeMode === "user" ? "Continue to node definition" : "Generate HAZOP worksheet"}
        {!submitting && <ArrowRight className="h-4 w-4" />}
      </Button>
      {!ready && !backendDown && (
        <p className="mt-2 text-center text-[11px] text-slate-500">Add the {missing.join(", ")} to continue.</p>
      )}
    </Card>
  );
}
