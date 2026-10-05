"use client";

import type { BackendInfo, ModelKind, TwinOutput } from "./api";

type Range = { min: number; max: number };

type Variable = {
  key: string;
  label: string;
  unit: string;
  value: (r: TwinOutput) => number;
  range: (info: BackendInfo) => Range | undefined;
};

const VARIABLES: Variable[] = [
  { key: "U", label: "U", unit: "W/m²·K", value: (r) => r.U, range: (x) => x.output_ranges?.U },
  { key: "T_air_out", label: "Air out", unit: "°C", value: (r) => r.T_air_out, range: (x) => x.output_ranges?.T_air_out },
  { key: "T_water_out", label: "Water out", unit: "°C", value: (r) => r.T_water_out, range: (x) => x.output_ranges?.T_water_out },
  { key: "Q_kW", label: "Duty", unit: "kW", value: (r) => r.Q_kW, range: (x) => x.output_ranges?.Q_kW },
];

function short(n: number) {
  const abs = Math.abs(n);
  if (abs >= 10000) return `${(n / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })}k`;
  if (abs >= 1000) return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (abs >= 100) return n.toFixed(0);
  return n.toFixed(1);
}

function fallbackRange(v: Variable, results: TwinOutput[]): Range {
  const max = Math.max(...results.map((r) => v.value(r)));
  return { min: 0, max: max * 1.25 || 1 };
}

export default function ModelHistograms({
  results,
  info,
  selected,
  titles,
  onSelect,
}: {
  results: TwinOutput[];
  info: BackendInfo | null;
  selected: ModelKind;
  titles: Record<ModelKind, string>;
  onSelect: (m: ModelKind) => void;
}) {
  const ranges = Object.fromEntries(
    VARIABLES.map((v) => [v.key, (info && v.range(info)) || fallbackRange(v, results)]),
  ) as Record<string, Range>;

  return (
    <section className="panel model-hist">
      <div className="panel-head">
        <h3>Outputs per model</h3>
        <p>
          One histogram per model. Each bar shows where the value sits in its data.csv range (0% = lowest, 100% =
          highest seen in data); the actual value is written above the bar. Click a card to select that model.
        </p>
      </div>

      <div className="mh-grid">
        {results.map((r) => (
          <article
            key={r.model}
            className={`mh-card ${r.model} ${r.model === selected ? "active" : ""}`}
            onClick={() => onSelect(r.model)}
          >
            <header>
              <i aria-hidden />
              <h4>{titles[r.model]}</h4>
            </header>

            <div className="mh-plot">
              <div className="mh-axis" aria-hidden>
                <span>100%</span>
                <span>50%</span>
                <span>0%</span>
              </div>
              <div className="mh-bars">
                {VARIABLES.map((v) => {
                  const value = v.value(r);
                  const { min, max } = ranges[v.key];
                  const raw = ((value - min) / (max - min || 1)) * 100;
                  const pct = Math.min(Math.max(raw, 0), 100);
                  const outside = raw < 0 || raw > 100;
                  return (
                    <div
                      key={v.key}
                      className={`mh-col ${outside ? "outside" : ""}`}
                      title={`${v.label}: ${value.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${v.unit} · ${raw.toFixed(0)}% of data range (${short(min)} – ${short(max)})`}
                    >
                      <span className="mh-value">{short(value)}</span>
                      <span className="mh-track">
                        <span className="mh-bar" style={{ height: `${Math.max(pct, 1.5)}%` }} />
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="mh-labels">
              {VARIABLES.map((v) => (
                <span key={v.key}>
                  {v.label}
                  <small>{v.unit}</small>
                </span>
              ))}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
