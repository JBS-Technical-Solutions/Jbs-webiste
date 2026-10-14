"use client";

import clsx from "clsx";
import { ChevronDown, Funnel, Search, X } from "lucide-react";
import { Fragment, useMemo, useState } from "react";
import { bandFor, bandsOf, CC_LABEL, useRiskMatrix } from "@/lib/risk";
import type { HazopNode, RiskCode, Worksheet, WorksheetRow } from "@/lib/types";
import { RiskBadge } from "./ui";

export interface WorksheetFilter {
  risk: RiskCode[];
  search: string;
  cell: { c: number; l: number } | null;
  node: "all" | number;
}

const CC_STYLE: Record<string, string> = {
  S: "bg-rose-50 text-rose-700 ring-rose-200",
  E: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  A: "bg-sky-50 text-sky-700 ring-sky-200",
};

const RISK_ORDER: Record<RiskCode, number> = { L: 0, M: 1, H: 2, VH: 3 };

function maxRisk(node: HazopNode): RiskCode {
  let best: RiskCode = "L";
  node.deviations.forEach((d) => d.rows.forEach((r) => RISK_ORDER[r.risk.code] > RISK_ORDER[best] && (best = r.risk.code)));
  return best;
}

function rowText(dev: string, row: WorksheetRow, recs: Record<string, string>) {
  const source = row.source;
  return [
    dev,
    row.cause,
    ...row.consequences,
    ...row.safeguards,
    ...row.tags,
    ...row.recommendations.map((r) => `${r} ${recs[r] ?? ""}`),
    source?.file ?? "",
    source?.tag ?? "",
    ...(source?.review ?? []),
  ]
    .join(" ")
    .toLowerCase();
}

function splitTags(tag: string) {
  return tag
    .split(/\s*\/\s*|,\s*/)
    .map((t) => t.trim())
    .filter(Boolean);
}

function focusable(tag: string) {
  return /[A-Z]{1,4}-?\d/.test(tag) || /-[A-Z]\d/.test(tag);
}

const CC_ORDER = ["S", "E", "A"] as const;

function InlineText({
  value,
  onCommit,
  className,
  dark,
}: {
  value: string;
  onCommit: (value: string) => void;
  className?: string;
  dark?: boolean;
}) {
  const [draft, setDraft] = useState<string | null>(value === "" ? "" : null);
  if (draft === null) {
    return (
      <button
        type="button"
        onClick={() => setDraft(value)}
        title="Click to edit"
        className={clsx(
          "w-full rounded-md px-1 py-0.5 text-left transition",
          dark ? "hover:bg-white/10" : "hover:bg-white hover:ring-1 hover:ring-brand-200",
          className,
        )}
      >
        {value || <span className="text-slate-300">Click to add</span>}
      </button>
    );
  }
  const save = () => {
    const next = draft.trim();
    if (next !== value) onCommit(next);
    setDraft(null);
  };
  return (
    <textarea
      autoFocus
      rows={Math.min(8, Math.max(2, draft.split("\n").length + 1))}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={save}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          setDraft(null);
        } else if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          e.currentTarget.blur();
        }
      }}
      className={clsx(
        "w-full resize-y rounded-md px-1.5 py-1 text-[13px] leading-relaxed outline-none",
        dark
          ? "border border-white/30 bg-white/10 text-white ring-2 ring-white/20"
          : "border border-brand-300 bg-white text-slate-800 ring-2 ring-brand-100",
      )}
    />
  );
}

function EditableList({ items, onChange }: { items: string[]; onChange: (items: string[]) => void }) {
  return (
    <ol className="space-y-1">
      {items.map((item, i) => (
        <li key={`${i}-${item === "" ? "new" : "set"}`} className="group/item flex gap-1">
          <span className="mt-0.5 shrink-0 font-semibold text-slate-400">{i + 1}.</span>
          <InlineText
            value={item}
            onCommit={(v) => onChange(v ? items.map((x, j) => (j === i ? v : x)) : items.filter((_, j) => j !== i))}
            className="min-w-0 flex-1"
          />
          <button
            type="button"
            aria-label="Remove line"
            title="Remove line"
            onClick={() => onChange(items.filter((_, j) => j !== i))}
            className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded text-slate-300 opacity-0 transition hover:bg-rose-50 hover:text-rose-600 group-hover/item:opacity-100"
          >
            <X className="h-3 w-3" />
          </button>
        </li>
      ))}
      <li>
        <button
          type="button"
          onClick={() => onChange([...items, ""])}
          className="rounded-md px-1 py-0.5 text-[11px] font-medium text-brand-600 hover:bg-brand-50"
        >
          + Add line
        </button>
      </li>
    </ol>
  );
}

function CcEditor({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const on = new Set(value.split(/[,/ ]+/).filter(Boolean));
  return (
    <div className="flex flex-col items-center gap-1">
      {CC_ORDER.map((c) => (
        <button
          key={c}
          type="button"
          title={`${CC_LABEL[c] ?? c} — click to toggle`}
          onClick={() => {
            const next = new Set(on);
            if (next.has(c)) next.delete(c);
            else next.add(c);
            const picked = CC_ORDER.filter((x) => next.has(x));
            onChange((picked.length ? picked : ["S"]).join(","));
          }}
          className={clsx(
            "rounded-md px-1.5 py-0.5 text-[11px] font-bold ring-1 transition",
            on.has(c) ? CC_STYLE[c] : "bg-white text-slate-300 ring-slate-200 hover:text-slate-500",
          )}
        >
          {c}
        </button>
      ))}
    </div>
  );
}

function LevelSelect({ value, onChange, kind }: { value: number; onChange: (v: number) => void; kind: "C" | "L" }) {
  const matrix = useRiskMatrix();
  const items = kind === "C" ? matrix.severity : matrix.likelihood;
  return (
    <label
      title={`${kind === "C" ? "Consequence" : "Likelihood"}: ${items[value - 1]?.name} (click to change)`}
      className="relative inline-flex h-8 w-11 cursor-pointer items-center justify-center gap-0.5 rounded-lg border border-slate-200 bg-white text-sm font-semibold tabular-nums text-slate-800 transition hover:border-brand-300 hover:bg-brand-50/50 focus-within:border-brand-500 focus-within:ring-2 focus-within:ring-brand-100"
    >
      {value}
      <ChevronDown className="h-3 w-3 text-slate-400" />
      <select
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="absolute inset-0 cursor-pointer opacity-0"
        aria-label={kind === "C" ? "Consequence" : "Likelihood"}
      >
        {items.map((it) => (
          <option key={it.level} value={it.level}>
            {it.level} - {it.name}
          </option>
        ))}
      </select>
    </label>
  );
}

export default function WorksheetView({
  ws,
  filter,
  setFilter,
  onUpdate,
  onUpdateNode,
  onUpdateRec,
  onTag,
  onRec,
  onOpenSource,
}: {
  ws: Worksheet;
  filter: WorksheetFilter;
  setFilter: (f: WorksheetFilter | ((f: WorksheetFilter) => WorksheetFilter)) => void;
  onUpdate: (n: number, d: number, r: number, patch: Partial<Pick<WorksheetRow, "cause" | "consequences" | "safeguards" | "cc" | "c" | "l">>) => void;
  onUpdateNode: (n: number, patch: Partial<Pick<HazopNode, "title" | "boundary" | "design_intent" | "design_conditions">>) => void;
  onUpdateRec: (id: string, text: string) => void;
  onTag: (tag: string) => void;
  onRec: (id: string) => void;
  onOpenSource: (source: NonNullable<WorksheetRow["source"]>) => void;
}) {
  const matrix = useRiskMatrix();
  // First place each recommendation appears (worksheet order); later rows say "refer above".
  const firstRec = useMemo(() => {
    const m = new Map<string, string>();
    ws.nodes.forEach((n, ni) =>
      n.deviations.forEach((d, di) =>
        d.rows.forEach((r, ri) => r.recommendations.forEach((id) => !m.has(id) && m.set(id, `${ni}-${di}-${ri}`))),
      ),
    );
    return m;
  }, [ws]);

  const q = filter.search.trim().toLowerCase();
  const active = filter.risk.length > 0 || !!q || !!filter.cell;

  const visible = useMemo(
    () =>
      ws.nodes
        .map((node, ni) => ({
          node,
          ni,
          devs: node.deviations
            .map((dev, di) => ({
              dev,
              di,
              rows: dev.rows
                .map((row, ri) => ({ row, ri }))
                .filter(({ row }) => {
                  if (filter.risk.length && !filter.risk.includes(row.risk.code)) return false;
                  if (filter.cell && (row.c !== filter.cell.c || row.l !== filter.cell.l)) return false;
                  if (q && !rowText(dev.deviation, row, ws.recommendations).includes(q)) return false;
                  return true;
                }),
            }))
            .filter((d) => d.rows.length),
        }))
        .filter((n) => (filter.node === "all" || filter.node === n.ni) && n.devs.length),
    [ws, filter, q],
  );

  const shownRows = visible.reduce((a, n) => a + n.devs.reduce((b, d) => b + d.rows.length, 0), 0);

  return (
    <div className="space-y-6">
      {/* Toolbar */}
      <div className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
        <div className="flex flex-wrap items-center gap-2">
          <div className="scrollbar-thin flex max-w-full gap-1.5 overflow-x-auto">
            <button
              onClick={() => setFilter((f) => ({ ...f, node: "all" }))}
              className={clsx(
                "shrink-0 rounded-lg px-3 py-1.5 text-xs font-medium transition",
                filter.node === "all" ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200",
              )}
            >
              All nodes
            </button>
            {ws.nodes.map((n, i) => {
              const b = bandFor(maxRisk(n), matrix);
              return (
                <button
                  key={n.id}
                  onClick={() => setFilter((f) => ({ ...f, node: i }))}
                  title={n.title}
                  className={clsx(
                    "flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition",
                    filter.node === i ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200",
                  )}
                >
                  <span className="h-2 w-2 rounded-full" style={{ background: b.color, boxShadow: `0 0 0 1px ${b.ring}` }} />
                  Node {n.id}
                  <span className="hidden max-w-[180px] truncate font-normal opacity-70 xl:inline">&middot; {n.title}</span>
                </button>
              );
            })}
          </div>

          <div className="ml-auto flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
              <input
                value={filter.search}
                onChange={(e) => setFilter((f) => ({ ...f, search: e.target.value }))}
                placeholder="Search causes, tags, safeguards…"
                className="h-8 w-60 rounded-lg border border-slate-200 bg-slate-50 pl-8 pr-7 text-xs outline-none transition focus:border-brand-400 focus:bg-white focus:ring-2 focus:ring-brand-100"
              />
              {filter.search && (
                <button
                  onClick={() => setFilter((f) => ({ ...f, search: "" }))}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700"
                  aria-label="Clear search"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
            <div className="flex items-center gap-1 rounded-lg bg-slate-50 p-0.5 ring-1 ring-slate-200">
              <Funnel className="mx-1 h-3.5 w-3.5 text-slate-400" />
              {bandsOf(matrix).map((b) => {
                const on = filter.risk.includes(b.code);
                return (
                  <button
                    key={b.code}
                    onClick={() =>
                      setFilter((f) => ({
                        ...f,
                        cell: null,
                        risk: on ? f.risk.filter((x) => x !== b.code) : [...f.risk, b.code],
                      }))
                    }
                    title={`${b.name} risk`}
                    className={clsx("rounded-md px-2 py-1 text-[11px] font-semibold transition", on ? "shadow-sm" : "text-slate-500 hover:text-slate-800")}
                    style={on ? { background: b.color, color: b.text, boxShadow: `inset 0 0 0 1px ${b.ring}` } : undefined}
                  >
                    {b.code}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
        {active && (
          <div className="mt-2.5 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-2.5 text-xs text-slate-500">
            Showing <b className="text-slate-800">{shownRows}</b> matching causes
            {filter.cell && (
              <span className="rounded-full bg-brand-50 px-2 py-0.5 font-medium text-brand-700 ring-1 ring-brand-200">
                C{filter.cell.c} × L{filter.cell.l}
              </span>
            )}
            <button
              onClick={() => setFilter((f) => ({ ...f, risk: [], search: "", cell: null }))}
              className="font-medium text-brand-600 hover:underline"
            >
              Clear filters
            </button>
          </div>
        )}
        {!active && (
          <div className="mt-2.5 border-t border-slate-100 pt-2.5 text-[11px] text-slate-400">
            Click any wording, S / E / A, or a recommendation to edit it. C and L update the risk colour. Downloads include your edits.
          </div>
        )}
      </div>

      {visible.length === 0 && (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white py-16 text-center text-sm text-slate-500">
          No worksheet rows match these filters.
        </div>
      )}

      {visible.map(({ node, ni, devs }) => (
        <section key={node.id} className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          {/* Node header */}
          <div className="relative border-b border-slate-200 bg-gradient-to-r from-ink-950 via-brand-950 to-ink-900 px-5 py-4 text-white">
            <div className="bg-grid-dark absolute inset-0 opacity-60" />
            <div className="relative flex flex-wrap items-center gap-3">
              <span className="rounded-lg bg-white/10 px-2.5 py-1 text-xs font-semibold ring-1 ring-white/20">Node {node.id}</span>
              <h2 className="min-w-0 flex-1 text-base font-semibold sm:text-lg">
                <InlineText dark value={node.title} onCommit={(title) => title && onUpdateNode(ni, { title })} />
              </h2>
              <span className="ml-auto flex items-center gap-2 text-xs text-slate-300">
                Highest risk <RiskBadge code={maxRisk(node)} size="sm" />
              </span>
            </div>
          </div>
          <div className="grid gap-px bg-slate-200 md:grid-cols-3">
            {(
              [
                ["Node boundary", "boundary", node.boundary],
                ["Design intent", "design_intent", node.design_intent],
                ["Design conditions", "design_conditions", node.design_conditions],
              ] as const
            ).map(([label, key, text]) => (
              <div key={label} className="bg-slate-50/80 px-5 py-3.5">
                <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">{label}</div>
                <div className="mt-1 text-[13px] leading-relaxed text-slate-700">
                  <InlineText value={text} onCommit={(v) => onUpdateNode(ni, { [key]: v })} />
                </div>
              </div>
            ))}
          </div>

          {/* Worksheet table */}
          <div className="scrollbar-thin max-h-[72vh] overflow-auto">
            <table className="ws-table w-full min-w-[1240px] border-collapse text-[13px] leading-relaxed">
              <thead>
                <tr className="bg-[#E8F1FF] text-left text-[11px] font-semibold uppercase tracking-wider text-slate-600">
                  <th className="w-[150px] border-b border-r border-slate-200 px-3 py-2.5">Deviation</th>
                  <th className="w-[200px] border-b border-r border-slate-200 px-3 py-2.5">Causes</th>
                  <th className="w-[255px] border-b border-r border-slate-200 px-3 py-2.5">Consequences</th>
                  <th className="w-[46px] border-b border-r border-slate-200 px-2 py-2.5 text-center" title="Consequence category">CC</th>
                  <th className="w-[240px] border-b border-r border-slate-200 px-3 py-2.5">Safeguards</th>
                  <th className="w-[145px] border-b border-r border-slate-200 px-3 py-2.5">Tag #</th>
                  <th className="w-[60px] border-b border-r border-slate-200 px-2 py-2.5 text-center" title="Consequence (severity) 1-5">C</th>
                  <th className="w-[60px] border-b border-r border-slate-200 px-2 py-2.5 text-center" title="Likelihood 1-5">L</th>
                  <th className="w-[74px] border-b border-r border-slate-200 px-2 py-2.5 text-center">Risk</th>
                  <th className="w-[300px] border-b border-slate-200 px-3 py-2.5">Recommendations</th>
                </tr>
              </thead>
              <tbody>
                {devs.map(({ dev, di, rows }) => (
                  <Fragment key={di}>
                    {rows.map(({ row, ri }, idx) => {
                      const key = `${ni}-${di}-${ri}`;
                      return (
                        <tr
                          key={key}
                          className={clsx(
                            "group align-top transition-colors",
                            row.source && row.source.verified === false ? "bg-rose-50 hover:bg-rose-100/70" : "hover:bg-brand-50/30",
                          )}
                        >
                          {idx === 0 && (
                            <td rowSpan={rows.length} className="border-b border-r border-slate-200 bg-slate-50/60 px-3 py-3">
                              <div className="font-mono text-[11px] font-semibold text-brand-600">{dev.deviation.split(" ")[0]}</div>
                              <div className="mt-0.5 font-semibold text-slate-900">{dev.deviation.split(" ").slice(1).join(" ")}</div>
                            </td>
                          )}
                          <td className="border-b border-r border-slate-200 px-3 py-3 text-slate-800">
                            <div className="flex gap-1">
                              <span className="mt-0.5 shrink-0 font-semibold text-slate-400">{ri + 1}.</span>
                              <InlineText value={row.cause} onCommit={(cause) => cause && onUpdate(ni, di, ri, { cause })} className="min-w-0 flex-1" />
                            </div>
                            {row.source && (
                              <div className="mt-1.5 flex flex-wrap items-center gap-1">
                                <button
                                  type="button"
                                  onClick={() => onOpenSource(row.source!)}
                                  title="Open this drawing"
                                  className="max-w-full truncate rounded-md bg-white px-1.5 py-0.5 text-left text-[10px] font-medium text-slate-600 ring-1 ring-slate-200 transition hover:bg-brand-50 hover:text-brand-700 hover:ring-brand-300"
                                >
                                  {row.source.file} · p.{row.source.page + 1}
                                  {row.source.tag ? ` · ${row.source.tag}` : ""}
                                </button>
                                {row.source.review.length > 0 && (
                                  <span
                                    title={row.source.review.join("\n")}
                                    className="rounded-full bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800 ring-1 ring-amber-200"
                                  >
                                    Needs review
                                  </span>
                                )}
                              </div>
                            )}
                          </td>
                          <td className="border-b border-r border-slate-200 px-3 py-3 text-slate-700">
                            <EditableList items={row.consequences} onChange={(consequences) => onUpdate(ni, di, ri, { consequences })} />
                          </td>
                          <td className="border-b border-r border-slate-200 px-2 py-3 text-center">
                            <CcEditor value={row.cc} onChange={(cc) => onUpdate(ni, di, ri, { cc })} />
                          </td>
                          <td className="border-b border-r border-slate-200 px-3 py-3 text-slate-700">
                            <EditableList items={row.safeguards} onChange={(safeguards) => onUpdate(ni, di, ri, { safeguards })} />
                          </td>
                          <td className="border-b border-r border-slate-200 px-3 py-3">
                            <div className="flex flex-col items-start gap-1">
                              {row.tags.map((t, i) => (
                                <div key={i} className="flex flex-wrap gap-1">
                                  {splitTags(t).map((tag) =>
                                    focusable(tag) ? (
                                      <button
                                        key={tag}
                                        onClick={() => onTag(tag)}
                                        title="Show on P&ID"
                                        className="whitespace-nowrap rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] font-medium text-slate-700 ring-1 ring-inset ring-slate-200 transition hover:bg-brand-50 hover:text-brand-700 hover:ring-brand-300"
                                      >
                                        {tag}
                                      </button>
                                    ) : (
                                      <span key={tag} className="px-1 font-mono text-[11px] text-slate-400">
                                        {tag}
                                      </span>
                                    ),
                                  )}
                                </div>
                              ))}
                            </div>
                          </td>
                          <td className="border-b border-r border-slate-200 px-2 py-3 text-center">
                            <LevelSelect kind="C" value={row.c} onChange={(v) => onUpdate(ni, di, ri, { c: v })} />
                          </td>
                          <td className="border-b border-r border-slate-200 px-2 py-3 text-center">
                            <LevelSelect kind="L" value={row.l} onChange={(v) => onUpdate(ni, di, ri, { l: v })} />
                          </td>
                          <td className="border-b border-r border-slate-200 px-2 py-3 text-center">
                            <RiskBadge code={row.risk.code} score={row.risk.score} />
                          </td>
                          <td className="border-b border-slate-200 px-3 py-3 text-slate-700">
                            {row.recommendations.length === 0 ? (
                              <span className="text-slate-300">—</span>
                            ) : (
                              <div className="space-y-2">
                                {row.recommendations.map((id) => (
                                  <div key={id} className="flex gap-2">
                                    <button
                                      onClick={() => onRec(id)}
                                      className="h-fit shrink-0 rounded-md bg-brand-50 px-1.5 py-0.5 font-mono text-[11px] font-semibold text-brand-700 ring-1 ring-inset ring-brand-200 transition hover:bg-brand-100"
                                    >
                                      {id}
                                    </button>
                                    {firstRec.get(id) === key ? (
                                      <InlineText value={ws.recommendations[id] ?? ""} onCommit={(text) => text && onUpdateRec(id, text)} className="min-w-0 flex-1" />
                                    ) : (
                                      <span className="italic text-slate-400">Refer above.</span>
                                    )}
                                  </div>
                                ))}
                              </div>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </div>
  );
}
