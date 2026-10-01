"use client";

import type { BackendInfo, ModelKind, TwinInputs, TwinOutput } from "./api";

type Range = { min: number; max: number };

type Variable = {
  key: string;
  label: string;
  unit: string;
  kind: "input" | "output";
  value: (i: TwinInputs, r: TwinOutput) => number;
  range: (info: BackendInfo) => Range | undefined;
};

const VARIABLES: Variable[] = [
  { key: "m_air", label: "Air flow", unit: "kg/h", kind: "input", value: (i) => i.m_air_kgh, range: (x) => x.training_ranges.m_air_kgh },
  { key: "m_water", label: "Water flow", unit: "kg/h", kind: "input", value: (i) => i.m_water_kgh, range: (x) => x.training_ranges.m_water_kgh },
  { key: "T_air_in", label: "Air in", unit: "°C", kind: "input", value: (i) => i.T_air_in, range: (x) => x.training_ranges.T_air_in },
  { key: "T_water_in", label: "Water in", unit: "°C", kind: "input", value: (i) => i.T_water_in, range: (x) => x.training_ranges.T_water_in },
  { key: "U", label: "U", unit: "W/m²·K", kind: "output", value: (_, r) => r.U, range: (x) => x.output_ranges?.U },
  { key: "T_air_out", label: "Air out", unit: "°C", kind: "output", value: (_, r) => r.T_air_out, range: (x) => x.output_ranges?.T_air_out },
  { key: "T_water_out", label: "Water out", unit: "°C", kind: "output", value: (_, r) => r.T_water_out, range: (x) => x.output_ranges?.T_water_out },
  { key: "Q_kW", label: "Duty", unit: "kW", kind: "output", value: (_, r) => r.Q_kW, range: (x) => x.output_ranges?.Q_kW },
];

const INPUT_COUNT = VARIABLES.filter((v) => v.kind === "input").length;

function short(n: number) {
  const abs = Math.abs(n);
  if (abs >= 10000) return `${(n / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })}k`;
  if (abs >= 1000) return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (abs >= 100) return n.toFixed(0);
  return n.toFixed(1);
}

function fallbackRange(key: string, results: TwinOutput[], inputs: TwinInputs): Range {
  const v = VARIABLES.find((x) => x.key === key)!;
  const max = Math.max(...results.map((r) => v.value(inputs, r)));
  return { min: 0, max: max * 1.25 || 1 };
}

export default function ModelHistograms({
  results,
  inputs,
  info,
  selected,
  titles,
  onSelect,
}: {
  results: TwinOutput[];
  inputs: TwinInputs;
  info: BackendInfo | null;
  selected: ModelKind;
  titles: Record<ModelKind, string>;
  onSelect: (m: ModelKind) => void;
}) {
  const ranges = Object.fromEntries(
    VARIABLES.map((v) => [v.key, (info && v.range(info)) || fallbackRange(v.key, results, inputs)]),
  ) as Record<string, Range>;

  return (
    <section className="panel model-hist">
      <div className="panel-head">
        <h3>Inputs &amp; outputs per model</h3>
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
                {VARIABLES.map((v, idx) => {
                  const value = v.value(inputs, r);
                  const { min, max } = ranges[v.key];
                  const raw = ((value - min) / (max - min || 1)) * 100;
                  const pct = Math.min(Math.max(raw, 0), 100);
                  const outside = raw < 0 || raw > 100;
                  return (
                    <div
                      key={v.key}
                      className={`mh-col ${v.kind} ${idx === INPUT_COUNT ? "split" : ""} ${outside ? "outside" : ""}`}
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
              {VARIABLES.map((v, idx) => (
                <span key={v.key} className={`${v.kind} ${idx === INPUT_COUNT ? "split" : ""}`}>
                  {v.label}
                  <small>{v.unit}</small>
                </span>
              ))}
            </div>

            <footer>
              <span className="mh-key input">Inputs</span>
              <span className="mh-key output">Outputs</span>
            </footer>
          </article>
        ))}
      </div>
    </section>
  );
}
