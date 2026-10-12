"use client";

import clsx from "clsx";
import { ArrowRight, ListTree, LoaderCircle, Minus, Plus, Trash2, TriangleAlert, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useMemo, useState } from "react";
import { imageUrl, submitNodes } from "@/lib/api";
import type { Box, Job, NodePlan } from "@/lib/types";
import { Button, Logo } from "./ui";

const COLORS = ["#2545eb", "#db2777", "#059669", "#d97706", "#9333ea", "#0891b2", "#dc2626", "#65a30d"];
const ZOOMS = [1, 1.5, 2, 3];

type Kind = "Equipment" | "Instrument" | "Line";

interface Candidate {
  tag: string;
  kind: Kind;
  sub: string;
  boxes: Box[];
}

interface Draft extends NodePlan {
  uid: number;
}

const draft = (uid: number, n: Partial<NodePlan> = {}): Draft => ({ title: "", tags: [], design_intent: "", ...n, uid });

export default function NodeEditor({ job, onSubmitted, onCancel }: { job: Job; onSubmitted: (job: Job) => void; onCancel: () => void }) {
  const review = job.review!;
  const ext = review.extraction;
  const [nodes, setNodes] = useState<Draft[]>(() =>
    review.proposed_nodes.length ? review.proposed_nodes.map((n, i) => draft(i + 1, n)) : [draft(1)],
  );
  const [active, setActive] = useState(nodes[0].uid);
  const [zoom, setZoom] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [hovered, setHovered] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const candidates = useMemo<Candidate[]>(() => {
    const out: Candidate[] = [];
    const seen = new Set<string>();
    const add = (c: Candidate) => !seen.has(c.tag) && (seen.add(c.tag), out.push(c));
    ext.equipment.filter((e) => !e.offpage).forEach((e) => add({ tag: e.tag, kind: "Equipment", sub: e.description || e.kind, boxes: e.boxes?.length ? e.boxes : [e.box] }));
    ext.instruments.forEach((i) => add({ tag: i.tag, kind: "Instrument", sub: i.description, boxes: [i.box] }));
    ext.lines.forEach((l) => add({ tag: l.tag, kind: "Line", sub: l.service_name ?? l.service, boxes: l.boxes?.length ? l.boxes : [l.box] }));
    return out;
  }, [ext]);

  const owner = useMemo(() => {
    const m = new Map<string, number>();
    nodes.forEach((n, i) => n.tags.forEach((t) => !m.has(t) && m.set(t, i)));
    return m;
  }, [nodes]);

  const activeIndex = Math.max(0, nodes.findIndex((n) => n.uid === active));
  const color = (i: number) => COLORS[i % COLORS.length];

  const update = (uid: number, patch: Partial<NodePlan>) => setNodes((ns) => ns.map((n) => (n.uid === uid ? { ...n, ...patch } : n)));
  const toggleTag = (uid: number, tag: string) =>
    setNodes((ns) => ns.map((n) => (n.uid === uid ? { ...n, tags: n.tags.includes(tag) ? n.tags.filter((t) => t !== tag) : [...n.tags, tag] } : n)));
  const addNode = () => {
    const n = draft(Math.max(0, ...nodes.map((x) => x.uid)) + 1);
    setNodes((ns) => [...ns, n]);
    setActive(n.uid);
  };
  const removeNode = (uid: number) => {
    const rest = nodes.filter((n) => n.uid !== uid);
    setNodes(rest);
    if (uid === active && rest.length) setActive(rest[Math.max(0, activeIndex - 1)].uid);
  };

  const empty = nodes.findIndex((n) => n.tags.length === 0);
  const canSubmit = nodes.length > 0 && empty === -1 && !submitting;

  const submit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      onSubmitted(await submitNodes(job.id, nodes));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col bg-slate-50">
      <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/85 backdrop-blur-md">
        <div className="mx-auto flex max-w-[1600px] items-center gap-4 px-4 py-3 sm:px-6">
          <Logo />
          <div className="hidden h-8 w-px bg-slate-200 md:block" />
          <div className="hidden min-w-0 flex-1 md:block">
            <div className="truncate text-sm font-semibold text-slate-900">Define HAZOP nodes</div>
            <div className="truncate text-xs text-slate-500">{job.filename}</div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="ghost" size="md" onClick={onCancel}>
              <X className="h-4 w-4" /> Cancel
            </Button>
            <Button size="md" disabled={!canSubmit} onClick={submit}>
              {submitting ? <LoaderCircle className="h-4 w-4 animate-spin" /> : null}
              Generate worksheet
              {!submitting && <ArrowRight className="h-4 w-4" />}
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto grid w-full max-w-[1600px] flex-1 gap-4 px-4 pb-10 pt-5 sm:px-6 xl:grid-cols-[1fr_420px]">
        <div className="xl:col-span-2">
          <h1 className="text-xl font-semibold tracking-tight text-slate-900">Review the proposed nodes</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            Each node is built from the equipment, instruments and lines you assign to it. Click a tag on the drawing to add it to
            or remove it from the selected node.
          </p>
        </div>

        {/* Drawing */}
        <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-3 py-2">
            <span className="flex items-center gap-1.5 text-xs font-medium text-slate-600">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: color(activeIndex) }} />
              Editing Node {activeIndex + 1}
            </span>
            <span className="text-[11px] text-slate-400">&middot; grey boxes are tags not yet in any node</span>
            <div className="ml-auto flex items-center gap-1">
              <button
                onClick={() => setZoom((z) => Math.max(0, z - 1))}
                className="grid h-8 w-8 place-items-center rounded-lg text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"
                aria-label="Zoom out"
              >
                <Minus className="h-4 w-4" />
              </button>
              <span className="w-12 text-center text-xs tabular-nums text-slate-500">{ZOOMS[zoom] * 100}%</span>
              <button
                onClick={() => setZoom((z) => Math.min(ZOOMS.length - 1, z + 1))}
                className="grid h-8 w-8 place-items-center rounded-lg text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50"
                aria-label="Zoom in"
              >
                <Plus className="h-4 w-4" />
              </button>
            </div>
          </div>
          <div className="scrollbar-thin h-[70vh] min-h-[460px] overflow-auto bg-slate-100">
            <div className="relative" style={{ width: `${ZOOMS[zoom] * 100}%` }}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={imageUrl(review.image.url)}
                alt="P&ID"
                draggable={false}
                onLoad={() => setLoaded(true)}
                className="block w-full select-none bg-white"
              />
              {!loaded && <div className="absolute inset-0 animate-pulse bg-slate-200/60" />}
              {loaded &&
                candidates.flatMap((c) =>
                  c.boxes.map((b, bi) => {
                    const own = owner.get(c.tag);
                    const inActive = nodes[activeIndex]?.tags.includes(c.tag);
                    const col = own !== undefined ? color(own) : "#64748b";
                    const hot = hovered === c.tag;
                    const pad = 0.002;
                    return (
                      <button
                        key={`${c.tag}-${bi}`}
                        type="button"
                        title={`${c.tag} · ${c.kind}${c.sub ? ` · ${c.sub}` : ""}`}
                        onClick={() => toggleTag(active, c.tag)}
                        onMouseEnter={() => setHovered(c.tag)}
                        onMouseLeave={() => setHovered(null)}
                        className="absolute cursor-pointer rounded-[2px] transition-[background-color,box-shadow] duration-150"
                        style={{
                          left: `${(b[0] - pad) * 100}%`,
                          top: `${(b[1] - pad) * 100}%`,
                          width: `${(b[2] - b[0] + 2 * pad) * 100}%`,
                          height: `${(b[3] - b[1] + 2 * pad) * 100}%`,
                          background: `${col}${inActive || hot ? "40" : own !== undefined ? "22" : "10"}`,
                          boxShadow: `0 0 0 ${inActive ? 2 : 1}px ${col}${own !== undefined || hot ? "" : "80"}`,
                          zIndex: inActive ? 3 : hot ? 2 : 1,
                        }}
                      />
                    );
                  }),
                )}
            </div>
          </div>
        </div>

        {/* Node list */}
        <div className="flex flex-col gap-3">
          <AnimatePresence initial={false}>
            {nodes.map((n, i) => {
              const isActive = n.uid === active;
              const listId = `tags-${n.uid}`;
              return (
                <motion.div
                  key={n.uid}
                  layout
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, height: 0 }}
                  onClick={() => setActive(n.uid)}
                  className={clsx(
                    "rounded-2xl border bg-white p-3.5 shadow-sm transition",
                    isActive ? "border-brand-400 ring-2 ring-brand-100" : "cursor-pointer border-slate-200 hover:border-slate-300",
                  )}
                >
                  <div className="flex items-center gap-2">
                    <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: color(i) }} />
                    <span className="text-xs font-semibold text-slate-500">Node {i + 1}</span>
                    {n.tags.length === 0 && (
                      <span className="flex items-center gap-1 text-[11px] font-medium text-amber-700">
                        <TriangleAlert className="h-3 w-3" /> add at least one tag
                      </span>
                    )}
                    <button
                      type="button"
                      aria-label={`Delete node ${i + 1}`}
                      disabled={nodes.length === 1}
                      onClick={(e) => {
                        e.stopPropagation();
                        removeNode(n.uid);
                      }}
                      className="ml-auto grid h-7 w-7 place-items-center rounded-lg text-slate-400 transition hover:bg-rose-50 hover:text-rose-600 disabled:opacity-30"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <input
                    value={n.title}
                    onChange={(e) => update(n.uid, { title: e.target.value })}
                    placeholder="Node title, e.g. Compressor suction scrubber"
                    className="mt-2 h-9 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm font-medium text-slate-900 outline-none transition placeholder:font-normal placeholder:text-slate-400 focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
                  />
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {n.tags.map((t) => (
                      <span
                        key={t}
                        onMouseEnter={() => setHovered(t)}
                        onMouseLeave={() => setHovered(null)}
                        className="inline-flex items-center gap-1 rounded-md bg-slate-100 py-0.5 pl-1.5 pr-0.5 font-mono text-[11px] font-medium text-slate-700 ring-1 ring-inset ring-slate-200"
                      >
                        {t}
                        <button
                          type="button"
                          aria-label={`Remove ${t}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleTag(n.uid, t);
                          }}
                          className="grid h-4 w-4 place-items-center rounded text-slate-400 hover:bg-white hover:text-slate-700"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </span>
                    ))}
                    <input
                      list={listId}
                      placeholder="+ add tag"
                      onKeyDown={(e) => {
                        if (e.key !== "Enter") return;
                        const v = e.currentTarget.value.trim().toUpperCase();
                        const c = candidates.find((x) => x.tag.toUpperCase() === v);
                        if (c && !n.tags.includes(c.tag)) toggleTag(n.uid, c.tag);
                        e.currentTarget.value = "";
                      }}
                      onChange={(e) => {
                        const c = candidates.find((x) => x.tag === e.target.value);
                        if (c) {
                          if (!n.tags.includes(c.tag)) toggleTag(n.uid, c.tag);
                          e.target.value = "";
                        }
                      }}
                      className="h-6 w-28 rounded-md border border-dashed border-slate-300 bg-white px-1.5 font-mono text-[11px] outline-none focus:border-brand-400"
                    />
                    <datalist id={listId}>
                      {candidates
                        .filter((c) => !n.tags.includes(c.tag))
                        .map((c) => (
                          <option key={c.tag} value={c.tag}>
                            {c.kind}
                            {c.sub ? ` · ${c.sub}` : ""}
                          </option>
                        ))}
                    </datalist>
                  </div>
                  <div className="mt-2.5 text-[11px] font-medium text-slate-500">
                    Design intent <span className="font-normal text-slate-400">&middot; leave blank to use the suggestion</span>
                  </div>
                  <textarea
                    value={n.design_intent}
                    onChange={(e) => update(n.uid, { design_intent: e.target.value })}
                    placeholder={n.auto_intent || "Written from the node's tags"}
                    rows={2}
                    className="mt-1 w-full resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 outline-none transition placeholder:text-slate-400 focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
                  />
                </motion.div>
              );
            })}
          </AnimatePresence>

          <Button variant="secondary" onClick={addNode}>
            <Plus className="h-4 w-4" /> Add node
          </Button>

          {error && (
            <div className="flex items-start gap-2 rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-700 ring-1 ring-rose-200">
              <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {error}
            </div>
          )}

          <div className="flex items-start gap-2 rounded-xl bg-white px-3 py-2.5 text-[11px] leading-relaxed text-slate-500 ring-1 ring-slate-200">
            <ListTree className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-600" />
            Deviations, causes and safeguards are generated for the equipment, control valves, relief devices and lines in each
            node. Leave the title or design intent blank to let the engine write them.
          </div>
        </div>
      </main>
    </div>
  );
}
