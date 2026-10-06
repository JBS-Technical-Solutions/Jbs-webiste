"use client";

import type { CSSProperties } from "react";

export type CurveSeries<K extends string> = {
  model: K;
  label: string;
  color: string;
  points: { flow_kgh: number; brake_kW: number | null }[];
};

const BOX = { x0: 64, x1: 700, y0: 18, y1: 250 };

function niceStep(span: number, ticks = 5) {
  const raw = span / ticks;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  return (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
}

function axis(lo: number, hi: number, ticks = 5) {
  const step = niceStep(hi - lo || 1, ticks);
  const min = Math.floor(lo / step) * step;
  const max = Math.ceil(hi / step) * step;
  return { min, max, ticks: Array.from({ length: Math.round((max - min) / step) + 1 }, (_, i) => min + i * step) };
}

function short(n: number) {
  return Math.abs(n) >= 1000 ? `${Number((n / 1000).toFixed(1))}k` : `${Number(n.toFixed(6))}`;
}

export default function PumpCurve<K extends string>({
  series,
  selected,
  onSelect,
  operating,
}: {
  series: CurveSeries<K>[];
  selected: K;
  onSelect: (m: K) => void;
  operating?: { flow_kgh: number; brake_kW: number } | null;
}) {
  const pts = series.flatMap((s) => s.points).filter((p): p is { flow_kgh: number; brake_kW: number } => p.brake_kW != null);
  const flows = pts.map((p) => p.flow_kgh).concat(operating ? [operating.flow_kgh] : []);
  const powers = pts.map((p) => p.brake_kW).concat(operating ? [operating.brake_kW] : [], [0]);
  const xa = axis(Math.min(...flows), Math.max(...flows), 6);
  const ya = axis(Math.min(...powers), Math.max(...powers) * 1.05);

  const x = (f: number) => BOX.x0 + ((f - xa.min) / (xa.max - xa.min)) * (BOX.x1 - BOX.x0);
  const y = (p: number) => BOX.y1 - ((p - ya.min) / (ya.max - ya.min)) * (BOX.y1 - BOX.y0);

  const ordered = [...series.filter((s) => s.model !== selected), ...series.filter((s) => s.model === selected)];
  const opColor = series.find((s) => s.model === selected)?.color ?? "#fff";

  return (
    <section className="panel pc-panel">
      <div className="panel-head">
        <h3>Brake power vs flow</h3>
        <p>
          Every model swept across the data&apos;s flow range at your suction and discharge pressures and density. The
          ringed point is the current operating point of the selected model. Click a legend entry to select a model.
        </p>
      </div>

      <svg viewBox="0 0 720 290" className="pc-chart" role="img" aria-label="Brake power versus water flow per model">
        {ya.ticks.map((t) => (
          <g key={t}>
            <line x1={BOX.x0} x2={BOX.x1} y1={y(t)} y2={y(t)} className="pc-grid" />
            <text x={BOX.x0 - 8} y={y(t) + 4} textAnchor="end" className="pc-axis">
              {short(t)}
            </text>
          </g>
        ))}
        {xa.ticks.map((t) => (
          <text key={t} x={x(t)} y={BOX.y1 + 18} textAnchor="middle" className="pc-axis">
            {short(t)}
          </text>
        ))}
        <text x={(BOX.x0 + BOX.x1) / 2} y={BOX.y1 + 36} textAnchor="middle" className="pc-axis-title">
          Water flow (kg/h)
        </text>
        <text
          x="14"
          y={(BOX.y0 + BOX.y1) / 2}
          textAnchor="middle"
          transform={`rotate(-90 14 ${(BOX.y0 + BOX.y1) / 2})`}
          className="pc-axis-title"
        >
          Brake power (kW)
        </text>

        {ordered.map((s) => {
          const line = s.points.filter((p) => p.brake_kW != null) as { flow_kgh: number; brake_kW: number }[];
          return (
            <g
              key={s.model}
              className={`pc-series ${s.model === selected ? "active" : ""}`}
              style={{ color: s.color }}
              onClick={() => onSelect(s.model)}
            >
              <polyline points={line.map((p) => `${x(p.flow_kgh)},${y(p.brake_kW)}`).join(" ")} />
            </g>
          );
        })}

        {operating && (
          <g className="pc-operating" style={{ color: opColor }}>
            <line x1={x(operating.flow_kgh)} x2={x(operating.flow_kgh)} y1={BOX.y1} y2={y(operating.brake_kW)} />
            <circle cx={x(operating.flow_kgh)} cy={y(operating.brake_kW)} r="9" className="pc-ring" />
            <circle cx={x(operating.flow_kgh)} cy={y(operating.brake_kW)} r="4" className="pc-dot" />
            <text
              x={x(operating.flow_kgh) + (x(operating.flow_kgh) > BOX.x1 - 150 ? -14 : 14)}
              y={y(operating.brake_kW) - 10}
              textAnchor={x(operating.flow_kgh) > BOX.x1 - 150 ? "end" : "start"}
              className="pc-op-label"
            >
              {operating.brake_kW.toFixed(2)} kW @ {operating.flow_kgh.toLocaleString()} kg/h
            </text>
          </g>
        )}
      </svg>

      <div className="pc-legend">
        {series.map((s) => (
          <button
            key={s.model}
            type="button"
            className={s.model === selected ? "active" : ""}
            style={{ "--lc": s.color } as CSSProperties}
            aria-pressed={s.model === selected}
            onClick={() => onSelect(s.model)}
          >
            <i aria-hidden />
            {s.label}
          </button>
        ))}
      </div>
    </section>
  );
}
