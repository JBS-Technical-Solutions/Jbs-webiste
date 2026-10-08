"use client";

import type { CSSProperties } from "react";

type Range = { min: number; max: number };

export type HistogramVariable<R> = {
  key: string;
  label: string;
  unit: string;
  color: string;
  value: (r: R) => number | null | undefined;
  range?: Range;
};

function short(n: number) {
  const abs = Math.abs(n);
  if (abs >= 10000) return `${(n / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })}k`;
  if (abs >= 1000) return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (abs >= 100) return n.toFixed(0);
  if (abs >= 1) return n.toFixed(1);
  return n.toPrecision(2);
}

function fallbackRange<R>(v: HistogramVariable<R>, results: R[]): Range {
  const values = results.map((r) => v.value(r)).filter((x): x is number => x != null && Number.isFinite(x));
  const max = values.length ? Math.max(...values) : 1;
  return { min: 0, max: max * 1.25 || 1 };
}

export default function ModelHistograms<K extends string, R extends { model: K }>({
  results,
  variables,
  selected,
  titles,
  onSelect,
}: {
  results: R[];
  variables: HistogramVariable<R>[];
  selected: K;
  titles: Record<K, string>;
  onSelect: (m: K) => void;
}) {
  const ranges = Object.fromEntries(variables.map((v) => [v.key, v.range ?? fallbackRange(v, results)])) as Record<
    string,
    Range
  >;

  return (
    <section className="panel model-hist">
      <div className="panel-head">
        <h3>Outputs per model</h3>
        <p>
          Each bar shows where the value sits in its data range (0% = lowest, 100% = highest); the actual value is
          written above the bar. Click a card to select that model.
        </p>
      </div>

      <div className="mh-grid" style={{ "--mh-cols": variables.length } as CSSProperties}>
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
                {variables.map((v) => {
                  const value = v.value(r);
                  const { min, max } = ranges[v.key];
                  const known = value != null && Number.isFinite(value);
                  const raw = known ? ((value - min) / (max - min || 1)) * 100 : 0;
                  const pct = Math.min(Math.max(raw, 0), 100);
                  const outside = known && (raw < 0 || raw > 100);
                  return (
                    <div
                      key={v.key}
                      className={`mh-col ${outside ? "outside" : ""}`}
                      style={{ "--vc": v.color } as CSSProperties}
                      title={
                        known
                          ? `${v.label}: ${value.toLocaleString(undefined, { maximumFractionDigits: 3 })} ${v.unit} · ${raw.toFixed(0)}% of data range (${short(min)} – ${short(max)})`
                          : `${v.label}: no result`
                      }
                    >
                      <span className="mh-value">{known ? short(value) : "—"}</span>
                      <span className="mh-track">
                        {known && <span className="mh-bar" style={{ height: `${Math.max(pct, 1.5)}%` }} />}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="mh-labels">
              {variables.map((v) => (
                <span key={v.key} style={{ "--vc": v.color } as CSSProperties}>
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
