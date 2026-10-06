"use client";

import type { CSSProperties } from "react";

export type ProfileSeries<K extends string> = {
  model: K;
  label: string;
  color: string;
  temps: (number | null | undefined)[];
};

const Z = [0, 0.2, 0.4, 0.6, 0.8, 1.0];
const BOX = { x0: 58, x1: 700, y0: 18, y1: 250 };

function niceStep(span: number) {
  const raw = span / 5;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  return (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
}

export default function AxialProfile<K extends string>({
  series,
  selected,
  onSelect,
  T_heat,
}: {
  series: ProfileSeries<K>[];
  selected: K;
  onSelect: (m: K) => void;
  T_heat: number;
}) {
  const values = [T_heat, ...series.flatMap((s) => s.temps)].filter(
    (v): v is number => v != null && Number.isFinite(v),
  );
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const step = niceStep(hi - lo || 10);
  const yMin = Math.floor((lo - step * 0.3) / step) * step;
  const yMax = Math.ceil((hi + step * 0.3) / step) * step;
  const ticks = Array.from({ length: Math.round((yMax - yMin) / step) + 1 }, (_, i) => yMin + i * step);

  const x = (z: number) => BOX.x0 + z * (BOX.x1 - BOX.x0);
  const y = (t: number) => BOX.y1 - ((t - yMin) / (yMax - yMin)) * (BOX.y1 - BOX.y0);

  const ordered = [...series.filter((s) => s.model !== selected), ...series.filter((s) => s.model === selected)];

  return (
    <section className="panel rx-profile">
      <div className="panel-head">
        <h3>Axial temperature profile</h3>
        <p>
          Bed temperature from the inlet (0 m) to the outlet (1 m) for every model. The inlet point is your feed
          temperature; the dashed line is the heating jacket. Click a legend entry to select that model.
        </p>
      </div>

      <svg viewBox="0 0 720 290" className="rx-chart" role="img" aria-label="Axial temperature profile per model">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={BOX.x0} x2={BOX.x1} y1={y(t)} y2={y(t)} className="rx-grid" />
            <text x={BOX.x0 - 8} y={y(t) + 4} textAnchor="end" className="rx-axis">
              {Number(t.toFixed(6))}
            </text>
          </g>
        ))}
        {Z.map((z) => (
          <text key={z} x={x(z)} y={BOX.y1 + 18} textAnchor="middle" className="rx-axis">
            {z.toFixed(1)}
          </text>
        ))}
        <text x={(BOX.x0 + BOX.x1) / 2} y={BOX.y1 + 36} textAnchor="middle" className="rx-axis-title">
          Bed position z (m)
        </text>
        <text
          x="14"
          y={(BOX.y0 + BOX.y1) / 2}
          textAnchor="middle"
          transform={`rotate(-90 14 ${(BOX.y0 + BOX.y1) / 2})`}
          className="rx-axis-title"
        >
          Temperature (°C)
        </text>

        <line x1={BOX.x0} x2={BOX.x1} y1={y(T_heat)} y2={y(T_heat)} className="rx-heater" />
        <text x={BOX.x1 - 4} y={y(T_heat) - 6} textAnchor="end" className="rx-heater-label">
          Jacket {T_heat.toFixed(0)}°C
        </text>

        {ordered.map((s) => {
          const pts = Z.map((z, i) => [z, s.temps[i]] as const).filter(
            (p): p is readonly [number, number] => p[1] != null && Number.isFinite(p[1]),
          );
          const active = s.model === selected;
          return (
            <g
              key={s.model}
              className={`rx-series ${active ? "active" : ""}`}
              style={{ color: s.color }}
              onClick={() => onSelect(s.model)}
            >
              <polyline points={pts.map(([z, t]) => `${x(z)},${y(t)}`).join(" ")} />
              {pts.map(([z, t]) => (
                <circle key={z} cx={x(z)} cy={y(t)} r={active ? 4.5 : 3}>
                  <title>
                    {s.label} · z {z.toFixed(1)} m · {t.toFixed(2)} °C
                  </title>
                </circle>
              ))}
            </g>
          );
        })}
      </svg>

      <div className="rx-legend">
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
