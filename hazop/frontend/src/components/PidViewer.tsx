"use client";

import clsx from "clsx";
import { ChevronLeft, ChevronRight, Crosshair, Eye, EyeOff, Maximize2, Minus, Plus, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent } from "react";
import { imageUrl } from "@/lib/api";
import type { Box, Extraction } from "@/lib/types";

type Layer = "equipment" | "instruments" | "lines" | "valves" | "connectors";

const LAYERS: { id: Layer; label: string; color: string; fill: string }[] = [
  { id: "equipment", label: "Equipment", color: "#2545eb", fill: "rgba(37,69,235,0.14)" },
  { id: "instruments", label: "Instruments", color: "#9333ea", fill: "rgba(147,51,234,0.14)" },
  { id: "lines", label: "Lines", color: "#059669", fill: "rgba(5,150,105,0.14)" },
  { id: "valves", label: "Valves", color: "#d97706", fill: "rgba(217,119,6,0.16)" },
  { id: "connectors", label: "Off-page", color: "#db2777", fill: "rgba(219,39,119,0.12)" },
];

interface Entity {
  key: string;
  layer: Layer;
  label: string;
  sub: string;
  detail: string[];
  boxes: Box[];
  page?: number;
}

function sameTag(label: string, tag: string) {
  const norm = (t: string) => t.toUpperCase().replace(/\s*\(.*\)$/, "").replace(/[^A-Z0-9]/g, "");
  const a = norm(label);
  const b = norm(tag);
  return !!b && (a === b || a.includes(b) || b.includes(a));
}

function buildEntities(ext: Extraction): Entity[] {
  const out: Entity[] = [];
  ext.equipment.forEach((e) =>
    out.push({
      key: e.id,
      layer: "equipment",
      label: e.tag,
      sub: e.description || e.kind,
      detail: [
        e.api14c ? `API 14C: ${e.api14c}` : "",
        ...Object.entries(e.design ?? {}).map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`),
        e.offpage ? "Off-page reference" : "",
      ].filter(Boolean),
      boxes: e.boxes?.length ? e.boxes : [e.box],
      page: e.page,
    }),
  );
  ext.instruments.forEach((i) =>
    out.push({
      key: i.id,
      layer: "instruments",
      label: i.tag,
      sub: i.description,
      detail: [
        i.set_point ? `Set point: ${i.set_point}` : "",
        i.set_psig ? `Set: ${i.set_psig} psig${i.fire_case ? " (fire case)" : ""}` : "",
        i.fail_action ? `Fail action: ${i.fail_action}` : "",
        i.voting ? `Voting: ${i.voting}` : "",
        i.remark ? `Remark: ${i.remark}` : "",
        i.inferred ? "Inferred from control loop" : "",
      ].filter(Boolean),
      boxes: [i.box],
      page: i.page,
    }),
  );
  ext.lines.forEach((l) =>
    out.push({
      key: l.id,
      layer: "lines",
      label: l.tag,
      sub: [l.service_name, l.rating].filter(Boolean).join(" · "),
      detail: [
        l.material ?? "",
        l.spec_known ? `${l.min_temp_f} to ${l.max_temp_f} °F, ${l.rating_psig} psig @ 100 °F` : `Spec ${l.spec} not in project specs`,
        l.sour ? "Sour service" : "",
      ].filter(Boolean),
      boxes: l.boxes?.length ? l.boxes : [l.box],
      page: l.page,
    }),
  );
  ext.valves.forEach((v) =>
    out.push({
      key: v.id,
      layer: "valves",
      label: v.code,
      sub: [v.type, v.size].filter(Boolean).join(" · "),
      detail: v.attributes.length ? [`Marked: ${v.attributes.join(", ")}`] : [],
      boxes: [v.box],
      page: v.page,
    }),
  );
  ext.connectors.forEach((c) =>
    out.push({
      key: c.id,
      layer: "connectors",
      label: `${c.direction === "source" ? "From" : "To"} ${c.description}`,
      sub: [c.line, c.ref].filter(Boolean).join(" · "),
      detail: [],
      boxes: [c.box],
      page: c.page,
    }),
  );
  return out;
}

interface View {
  s: number;
  x: number;
  y: number;
}

export default function PidViewer({
  image,
  extraction,
  focusTag,
  focusPage = null,
  onFocusHandled,
}: {
  image: { width: number; height: number; url: string; page_count?: number; pages?: { width: number; height: number }[] };
  extraction: Extraction;
  focusTag: string | null;
  focusPage?: number | null;
  onFocusHandled: () => void;
}) {
  const entities = useMemo(() => buildEntities(extraction), [extraction]);
  const pages = image.page_count ?? 1;
  const [page, setPage] = useState(() => {
    if (typeof focusPage === "number") return Math.max(0, Math.min(pages - 1, focusPage));
    if (!focusTag || pages <= 1) return 0;
    return entities.find((e) => sameTag(e.label, focusTag))?.page ?? 0;
  });
  const pending = useRef<string | null>(null);
  const [layers, setLayers] = useState<Record<Layer, boolean>>({
    equipment: true,
    instruments: true,
    lines: true,
    valves: true,
    connectors: true,
  });
  const [listLayer, setListLayer] = useState<Layer | "all">("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const wrapRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 800, h: 560 });
  const [view, setView] = useState<View>({ s: 1, x: 0, y: 0 });
  const [animate, setAnimate] = useState(false);
  const drag = useRef<{ x: number; y: number; vx: number; vy: number; moved: boolean } | null>(null);
  const interacted = useRef(false);
  const sheet = image.pages?.[page];
  const drawW = sheet?.width || image.width || 1;
  const drawH = sheet?.height || image.height || 1;

  const baseW = size.w;
  const baseH = (size.w * drawH) / drawW;

  const fitView = useCallback(
    (w: number, h: number): View => {
      const bh = (w * drawH) / drawW;
      const s = Math.min(1, h / bh);
      return { s, x: (w - w * s) / 2, y: (h - bh * s) / 2 };
    },
    [drawW, drawH],
  );

  const fit = () => {
    interacted.current = false;
    setAnimate(true);
    setView(fitView(size.w, size.h));
  };

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => {
      const { width, height } = e.contentRect;
      setSize({ w: width, h: height });
      if (interacted.current) return;
      setAnimate(false);
      setView(fitView(width, height));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [fitView]);

  const zoomAt = useCallback((factor: number, cx: number, cy: number, smooth = false) => {
    interacted.current = true;
    setAnimate(smooth);
    setView((v) => {
      const s = Math.min(12, Math.max(0.3, v.s * factor));
      const k = s / v.s;
      return { s, x: cx - (cx - v.x) * k, y: cy - (cy - v.y) * k };
    });
  }, []);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [zoomAt]);

  const focusEntity = (ent: Entity) => {
    const rect = wrapRef.current?.getBoundingClientRect();
    const w = rect?.width ?? size.w;
    const h = rect?.height ?? size.h;
    const bw = w;
    const bh = (w * drawH) / drawW;
    const b = ent.boxes[0];
    const cx = ((b[0] + b[2]) / 2) * bw;
    const cy = ((b[1] + b[3]) / 2) * bh;
    const s = Math.max(2.5, Math.min(5, (0.25 * w) / Math.max((b[2] - b[0]) * bw, 1)));
    interacted.current = true;
    setAnimate(true);
    setView({ s, x: w / 2 - cx * s, y: h / 2 - cy * s });
    setSelected(ent.key);
    setLayers((l) => ({ ...l, [ent.layer]: true }));
  };

  const showSheet = (next: number) => {
    const clamped = Math.max(0, Math.min(pages - 1, next));
    if (clamped === page) return;
    pending.current = null;
    interacted.current = false;
    setLoaded(false);
    setSelected(null);
    setPage(clamped);
  };

  const openEntity = (ent: Entity) => {
    if (ent.page !== undefined && ent.page !== page) {
      pending.current = ent.key;
      interacted.current = false;
      setLoaded(false);
      setPage(ent.page);
      return;
    }
    focusEntity(ent);
  };

  const onImageLoad = () => {
    setLoaded(true);
    const pendingKey = pending.current;
    pending.current = null;
    if (pendingKey) {
      const ent = entities.find((e) => e.key === pendingKey);
      if (ent) setTimeout(() => focusEntity(ent), 50);
      return;
    }
    if (!focusTag) {
      onFocusHandled();
      return;
    }
    const here = entities.filter((e) => e.page === undefined || e.page === page);
    const ent = here.find((e) => sameTag(e.label, focusTag)) ?? entities.find((e) => sameTag(e.label, focusTag));
    if (ent && ent.page !== undefined && ent.page !== page) {
      pending.current = ent.key;
      setPage(ent.page);
      return;
    }
    if (ent) {
      setTimeout(() => {
        focusEntity(ent);
        const item = document.getElementById(`ent-${ent.key}`);
        const list = item?.parentElement;
        if (item && list) list.scrollTo({ top: item.offsetTop - list.clientHeight / 2, behavior: "smooth" });
      }, 150);
    }
    onFocusHandled();
  };

  const onPointerDown = (e: RPointerEvent) => {
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, moved: false };
    interacted.current = true;
    setAnimate(false);
  };
  const onPointerMove = (e: RPointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
    setView((v) => ({ ...v, x: d.vx + dx, y: d.vy + dy }));
  };
  const onPointerUp = () => {
    if (drag.current && !drag.current.moved) setSelected(null);
    drag.current = null;
  };

  const q = query.trim().toLowerCase();
  const onPage = entities.filter((e) => e.page === undefined || e.page === page);
  const listed = entities.filter(
    (e) => (listLayer === "all" || e.layer === listLayer) && (!q || `${e.label} ${e.sub} sheet ${((e.page ?? 0) + 1)}`.toLowerCase().includes(q)),
  );
  const sel = entities.find((e) => e.key === selected);
  const counts = Object.fromEntries(LAYERS.map((l) => [l.id, onPage.filter((e) => e.layer === l.id).length])) as Record<Layer, number>;

  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
      {/* Viewer */}
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-3 py-2">
          {LAYERS.map((l) => (
            <button
              key={l.id}
              onClick={() => setLayers((s) => ({ ...s, [l.id]: !s[l.id] }))}
              className={clsx(
                "flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium ring-1 transition",
                layers[l.id] ? "bg-white text-slate-700 ring-slate-200" : "bg-slate-50 text-slate-400 ring-transparent",
              )}
            >
              {layers[l.id] ? <Eye className="h-3.5 w-3.5" style={{ color: l.color }} /> : <EyeOff className="h-3.5 w-3.5" />}
              {l.label}
              <span className="tabular-nums text-slate-400">{counts[l.id]}</span>
            </button>
          ))}
          <div className="ml-auto flex items-center gap-1">
            <span className="mr-1 hidden text-[11px] text-slate-400 lg:inline">Scroll to zoom · drag to pan</span>
            <button onClick={() => zoomAt(1 / 1.4, size.w / 2, size.h / 2, true)} className="grid h-8 w-8 place-items-center rounded-lg text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50" aria-label="Zoom out">
              <Minus className="h-4 w-4" />
            </button>
            <span className="w-12 text-center text-xs tabular-nums text-slate-500">{Math.round(view.s * 100)}%</span>
            <button onClick={() => zoomAt(1.4, size.w / 2, size.h / 2, true)} className="grid h-8 w-8 place-items-center rounded-lg text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50" aria-label="Zoom in">
              <Plus className="h-4 w-4" />
            </button>
            <button onClick={() => fit()} className="grid h-8 w-8 place-items-center rounded-lg text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50" aria-label="Fit to screen">
              <Maximize2 className="h-4 w-4" />
            </button>
            {pages > 1 && (
              <div className="ml-1 flex items-center gap-1 rounded-lg bg-slate-50 p-0.5 ring-1 ring-slate-200">
                <button type="button" onClick={() => showSheet(page - 1)} disabled={page === 0} className="grid h-7 w-7 place-items-center rounded-md text-slate-600 hover:bg-white disabled:opacity-30" aria-label="Previous sheet">
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <label className="flex items-center gap-1 px-1 text-[11px] text-slate-500">
                  Sheet
                  <input
                    type="number"
                    min={1}
                    max={pages}
                    value={page + 1}
                    onChange={(e) => showSheet((Number(e.target.value) || 1) - 1)}
                    className="h-7 w-14 rounded-md border border-slate-200 bg-white text-center text-xs font-semibold text-slate-800 outline-none focus:border-brand-400"
                    aria-label="Sheet number"
                  />
                  <span className="tabular-nums">/ {pages}</span>
                </label>
                <button type="button" onClick={() => showSheet(page + 1)} disabled={page === pages - 1} className="grid h-7 w-7 place-items-center rounded-md text-slate-600 hover:bg-white disabled:opacity-30" aria-label="Next sheet">
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            )}
          </div>
        </div>

        <div
          ref={wrapRef}
          className="relative h-[68vh] min-h-[460px] cursor-grab touch-none select-none overflow-hidden bg-slate-100 active:cursor-grabbing"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerLeave={onPointerUp}
          onDoubleClick={(e) => {
            const r = wrapRef.current!.getBoundingClientRect();
            zoomAt(2, e.clientX - r.left, e.clientY - r.top, true);
          }}
        >
          <div className="bg-grid absolute inset-0" />
          <div
            className={clsx("absolute left-0 top-0 origin-top-left", animate && "transition-transform duration-500 ease-out")}
            style={{ width: baseW, height: baseH, transform: `translate(${view.x}px, ${view.y}px) scale(${view.s})` }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              key={page}
              src={`${imageUrl(image.url)}?page=${page}`}
              alt={`P&ID sheet ${page + 1}`}
              draggable={false}
              onLoad={onImageLoad}
              className="pointer-events-none h-full w-full bg-white shadow-xl"
            />
            {loaded &&
              onPage
                .filter((e) => layers[e.layer])
                .flatMap((e) =>
                  e.boxes.map((b, i) => {
                    const L = LAYERS.find((l) => l.id === e.layer)!;
                    const isSel = selected === e.key;
                    const isHov = hovered === e.key;
                    const pad = 0.002;
                    return (
                      <div
                        key={`${e.key}-${i}`}
                        onPointerDown={(ev) => ev.stopPropagation()}
                        onClick={() => setSelected(e.key)}
                        onMouseEnter={() => setHovered(e.key)}
                        onMouseLeave={() => setHovered(null)}
                        className="absolute cursor-pointer rounded-[2px] transition-[background-color,box-shadow] duration-150"
                        style={{
                          left: `${(b[0] - pad) * 100}%`,
                          top: `${(b[1] - pad) * 100}%`,
                          width: `${(b[2] - b[0] + 2 * pad) * 100}%`,
                          height: `${(b[3] - b[1] + 2 * pad) * 100}%`,
                          background: isSel || isHov ? L.fill.replace(/0\.1\d/, "0.3") : L.fill,
                          boxShadow: `0 0 0 ${isSel ? 2 / view.s + 1 : 1 / view.s + 0.5}px ${L.color}`,
                          zIndex: isSel ? 3 : isHov ? 2 : 1,
                        }}
                      >
                        {(isSel || isHov) && i === 0 && (
                          <div
                            className="pointer-events-none absolute bottom-full left-0 mb-1 whitespace-nowrap rounded-md px-1.5 py-0.5 font-mono font-semibold text-white shadow-lg"
                            style={{ background: L.color, fontSize: `${12 / view.s}px`, transformOrigin: "bottom left" }}
                          >
                            {e.label}
                          </div>
                        )}
                      </div>
                    );
                  }),
                )}
          </div>
          {!loaded && <div className="absolute inset-0 animate-pulse bg-slate-200/60" />}

          {sel && (
            <div className="absolute bottom-3 left-3 max-w-sm rounded-xl bg-white/95 p-3.5 shadow-xl ring-1 ring-slate-200 backdrop-blur">
              <div className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: LAYERS.find((l) => l.id === sel.layer)!.color }} />
                <span className="font-mono text-sm font-semibold text-slate-900">{sel.label}</span>
              </div>
              {sel.sub && <div className="mt-0.5 text-xs text-slate-600">{sel.sub}</div>}
              {sel.detail.length > 0 && (
                <ul className="mt-2 space-y-0.5 text-[11px] text-slate-500">
                  {sel.detail.map((d) => (
                    <li key={d}>{d}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Entity list */}
      <div className="flex max-h-[calc(68vh+46px)] min-h-[506px] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 p-3">
          <div className="text-sm font-semibold text-slate-900">Extracted from the drawing</div>
          <div className="mt-0.5 text-xs text-slate-500">
            {pages > 1 ? `${onPage.length} on this sheet · ${entities.length} in the PDF` : `${entities.length} entities`} &middot; {extraction.token_count} text items
            {extraction.flags.sour_service && <span className="ml-1 rounded bg-amber-50 px-1 text-amber-700">sour service</span>}
          </div>
          <div className="relative mt-3">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Find a tag, line or valve…"
              className="h-8 w-full rounded-lg border border-slate-200 bg-slate-50 pl-8 pr-3 text-xs outline-none focus:border-brand-400 focus:bg-white focus:ring-2 focus:ring-brand-100"
            />
          </div>
          <div className="scrollbar-thin mt-2 flex gap-1 overflow-x-auto">
            {[{ id: "all" as const, label: "All" }, ...LAYERS].map((l) => (
              <button
                key={l.id}
                onClick={() => setListLayer(l.id)}
                className={clsx(
                  "shrink-0 rounded-md px-2 py-1 text-[11px] font-medium transition",
                  listLayer === l.id ? "bg-slate-900 text-white" : "text-slate-500 hover:bg-slate-100",
                )}
              >
                {l.label}
              </button>
            ))}
          </div>
        </div>
        <ul className="scrollbar-thin relative flex-1 divide-y divide-slate-100 overflow-y-auto">
          {listed.map((e) => {
            const L = LAYERS.find((l) => l.id === e.layer)!;
            return (
              <li key={e.key} id={`ent-${e.key}`}>
                <button
                  onClick={() => openEntity(e)}
                  onMouseEnter={() => setHovered(e.key)}
                  onMouseLeave={() => setHovered(null)}
                  className={clsx(
                    "group flex w-full items-start gap-2.5 px-3 py-2.5 text-left transition",
                    selected === e.key ? "bg-brand-50" : "hover:bg-slate-50",
                  )}
                >
                  <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full" style={{ background: L.color }} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-mono text-[12px] font-semibold text-slate-800">
                      {pages > 1 && e.page !== undefined && <span className="mr-1 text-slate-400">S{e.page + 1}</span>}
                      {e.label}
                    </span>
                    <span className="block truncate text-[11px] text-slate-500">{e.sub}</span>
                  </span>
                  <Crosshair className="mt-1 h-3.5 w-3.5 shrink-0 text-slate-300 opacity-0 transition group-hover:opacity-100" />
                </button>
              </li>
            );
          })}
          {listed.length === 0 && <li className="px-3 py-10 text-center text-xs text-slate-400">Nothing matches.</li>}
        </ul>
      </div>
    </div>
  );
}
