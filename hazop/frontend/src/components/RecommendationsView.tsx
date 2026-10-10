"use client";

import clsx from "clsx";
import { BookOpen, Check, Clipboard, ListChecks, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { bandFor } from "@/lib/risk";
import type { RiskCode, Worksheet } from "@/lib/types";
import { RiskBadge, SectionTitle } from "./ui";

export default function RecommendationsView({ ws, focus }: { ws: Worksheet; focus: string | null }) {
  const [query, setQuery] = useState("");
  const [copied, setCopied] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(focus);

  const info = useMemo(() => {
    const m = new Map<string, { refs: string[]; score: number; code: RiskCode | null; nodes: Set<number> }>();
    ws.nodes.forEach((n) =>
      n.deviations.forEach((d) =>
        d.rows.forEach((r) =>
          r.recommendations.forEach((id) => {
            const cur = m.get(id) ?? { refs: [], score: 0, code: null, nodes: new Set<number>() };
            const ref = d.deviation.split(" ")[0];
            if (!cur.refs.includes(ref)) cur.refs.push(ref);
            if (r.risk.score > cur.score) {
              cur.score = r.risk.score;
              cur.code = r.risk.code;
            }
            cur.nodes.add(n.id);
            m.set(id, cur);
          }),
        ),
      ),
    );
    return m;
  }, [ws]);

  useEffect(() => {
    if (!focus) return;
    setTimeout(() => document.getElementById(`rec-${focus}`)?.scrollIntoView({ block: "center", behavior: "smooth" }), 80);
    const t = setTimeout(() => setFlash(null), 2200);
    return () => clearTimeout(t);
  }, [focus]);

  const q = query.trim().toLowerCase();
  const recs = Object.entries(ws.recommendations).filter(([id, text]) => !q || `${id} ${text}`.toLowerCase().includes(q));

  const copy = async (id: string, text: string) => {
    await navigator.clipboard.writeText(`${id}: ${text}`);
    setCopied(id);
    setTimeout(() => setCopied(null), 1500);
  };

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_340px]">
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <SectionTitle
          icon={<ListChecks className="h-4 w-4" />}
          title="Recommendations"
          subtitle="Actions raised by the analysis, with the deviations they close and their highest risk"
          right={
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search recommendations…"
                className="h-8 w-56 rounded-lg border border-slate-200 bg-slate-50 pl-8 pr-3 text-xs outline-none focus:border-brand-400 focus:bg-white focus:ring-2 focus:ring-brand-100"
              />
            </div>
          }
        />
        <ul className="mt-5 space-y-3">
          {recs.map(([id, text]) => {
            const i = info.get(id);
            return (
              <li
                key={id}
                id={`rec-${id}`}
                className={clsx(
                  "group flex gap-4 rounded-xl border p-4 transition-all duration-500",
                  flash === id ? "border-brand-400 bg-brand-50 ring-4 ring-brand-100" : "border-slate-200 hover:border-slate-300 hover:shadow-sm",
                )}
              >
                <div className="shrink-0">
                  <span className="inline-block rounded-lg bg-slate-900 px-2 py-1 font-mono text-xs font-semibold text-white">{id}</span>
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm leading-relaxed text-slate-800">{text}</p>
                  <div className="mt-2.5 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
                    {i?.refs.map((r) => (
                      <span key={r} className="rounded-md bg-slate-100 px-1.5 py-0.5 font-mono font-medium text-slate-600">
                        {r}
                      </span>
                    ))}
                    {i && <span className="ml-1">Node {[...i.nodes].join(", ")}</span>}
                  </div>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-2">
                  {i?.code ? <RiskBadge code={i.code} score={i.score} /> : <span className="text-xs text-slate-300">—</span>}
                  <button
                    onClick={() => copy(id, text)}
                    className="flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] text-slate-400 opacity-0 transition hover:bg-slate-100 hover:text-slate-700 group-hover:opacity-100"
                  >
                    {copied === id ? <Check className="h-3 w-3 text-emerald-600" /> : <Clipboard className="h-3 w-3" />}
                    {copied === id ? "Copied" : "Copy"}
                  </button>
                </div>
              </li>
            );
          })}
          {recs.length === 0 && <li className="py-10 text-center text-sm text-slate-400">No recommendations match.</li>}
        </ul>
      </div>

      <div className="space-y-5">
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="text-sm font-semibold text-slate-900">By highest risk</div>
          <div className="mt-3 space-y-2">
            {(["VH", "H", "M", "L"] as RiskCode[]).map((code) => {
              const n = [...info.values()].filter((x) => x.code === code).length;
              const b = bandFor(code);
              return (
                <div key={code} className="flex items-center gap-3">
                  <RiskBadge code={code} size="sm" />
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${(n / Math.max(info.size, 1)) * 100}%`, background: b.color, boxShadow: "inset 0 0 0 1px rgba(0,0,0,0.08)" }}
                    />
                  </div>
                  <span className="w-6 text-right text-xs tabular-nums text-slate-600">{n}</span>
                </div>
              );
            })}
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <BookOpen className="h-4 w-4 text-brand-600" /> Assumptions &amp; basis
          </div>
          <ul className="mt-3 space-y-2 text-[13px] leading-relaxed text-slate-600">
            {ws.assumptions.map((a) => (
              <li key={a} className="flex gap-2">
                <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-slate-400" />
                {a}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
