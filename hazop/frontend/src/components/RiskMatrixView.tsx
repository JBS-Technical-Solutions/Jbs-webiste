"use client";

import clsx from "clsx";
import { Grid3x3 } from "lucide-react";
import { motion } from "motion/react";
import { bandFor, bandsOf, evaluate, useRiskMatrix } from "@/lib/risk";
import type { WorksheetRow } from "@/lib/types";
import { SectionTitle } from "./ui";

export default function RiskMatrixView({ rows, onCell }: { rows: WorksheetRow[]; onCell: (c: number, l: number) => void }) {
  const matrix = useRiskMatrix();
  const { severity, likelihood } = matrix;
  const count = (c: number, l: number) => rows.filter((r) => r.c === c && r.l === l).length;
  const max = Math.max(1, ...severity.flatMap((s) => likelihood.map((l) => count(s.level, l.level))));

  return (
    <div className="grid gap-5 xl:grid-cols-[1.2fr_1fr]">
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <SectionTitle
          icon={<Grid3x3 className="h-4 w-4" />}
          title={`Risk matrix ${severity.length} × ${likelihood.length}${matrix.scores ? "" : " (Risk = C × L)"}`}
          subtitle={`${matrix.source ? `From ${matrix.source} · ` : ""}Number of worksheet causes in each cell — click a cell to see those rows`}
        />
        <div className="mt-6 flex gap-3">
          <div className="flex w-6 items-center justify-center">
            <span className="-rotate-90 whitespace-nowrap text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Consequence
            </span>
          </div>
          <div className="flex-1">
            <div className="grid gap-1.5" style={{ gridTemplateColumns: `110px repeat(${likelihood.length}, minmax(0, 1fr))` }}>
              {[...severity].reverse().map((s) => (
                <div key={s.level} className="contents">
                  <div className="flex flex-col justify-center pr-2 text-right">
                    <span className="text-xs font-semibold text-slate-700">C{s.level}</span>
                    <span className="text-[11px] text-slate-400">{s.name}</span>
                  </div>
                  {likelihood.map((l) => {
                    const risk = evaluate(s.level, l.level, matrix);
                    const b = bandFor(risk.code, matrix);
                    const n = count(s.level, l.level);
                    return (
                      <motion.button
                        key={l.level}
                        whileHover={{ scale: 1.04 }}
                        whileTap={{ scale: 0.97 }}
                        disabled={!n}
                        onClick={() => onCell(s.level, l.level)}
                        className={clsx(
                          "relative flex aspect-[4/3] min-h-[64px] flex-col items-center justify-center rounded-xl transition-shadow",
                          n ? "cursor-pointer hover:shadow-lg" : "cursor-default",
                        )}
                        style={{ background: b.color, boxShadow: `inset 0 0 0 1px ${b.ring}`, color: b.text }}
                        title={matrix.scores ? `C${s.level}, L${l.level}: risk ${risk.score} (${risk.name})` : `C${s.level} × L${l.level} = ${risk.score} (${risk.name})`}
                      >
                        <span className="absolute left-2 top-1.5 text-[10px] font-semibold opacity-60">{risk.score}</span>
                        {n > 0 ? (
                          <span
                            className="grid place-items-center rounded-full bg-white/80 font-semibold tabular-nums shadow-sm ring-1 ring-black/5"
                            style={{ width: 26 + (n / max) * 18, height: 26 + (n / max) * 18, fontSize: 12 + (n / max) * 4 }}
                          >
                            {n}
                          </span>
                        ) : (
                          <span className="text-xs opacity-30">·</span>
                        )}
                      </motion.button>
                    );
                  })}
                </div>
              ))}
              <div />
              {likelihood.map((l) => (
                <div key={l.level} className="pt-1 text-center">
                  <div className="text-xs font-semibold text-slate-700">L{l.level}</div>
                  <div className="text-[11px] text-slate-400">{l.name}</div>
                </div>
              ))}
            </div>
            <div className="mt-2 text-center text-[11px] font-semibold uppercase tracking-wider text-slate-400">Likelihood</div>
          </div>
        </div>
        <div className="mt-6 flex flex-wrap gap-2">
          {bandsOf(matrix).map((b) => (
            <span
              key={b.code}
              className="inline-flex items-center gap-2 rounded-lg px-2.5 py-1 text-xs font-medium"
              style={{ background: b.color, color: b.text, boxShadow: `inset 0 0 0 1px ${b.ring}` }}
            >
              <b>{b.code}</b> {b.name}
            </span>
          ))}
        </div>
      </div>

      <div className="space-y-5">
        {[
          { title: "Consequence (C)", items: severity },
          { title: "Likelihood (L)", items: likelihood },
        ].map((t) => (
          <div key={t.title} className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
            <div className="border-b border-slate-200 bg-[#E8F1FF] px-4 py-2.5 text-xs font-semibold uppercase tracking-wider text-slate-600">
              {t.title}
            </div>
            <table className="w-full text-[13px]">
              <tbody>
                {t.items.map((it) => (
                  <tr key={it.level} className="border-b border-slate-100 last:border-0">
                    <td className="w-10 px-4 py-2.5 font-mono font-semibold text-slate-900">{it.level}</td>
                    <td className="w-28 py-2.5 font-medium text-slate-800">{it.name}</td>
                    <td className="py-2.5 pr-4 text-slate-500">{it.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </div>
  );
}
