"use client";

import type { CSSProperties } from "react";
import { type BackendInfo, MODEL_ORDER, type ModelKind, type OutputCol } from "./api";

const BARS: { key: OutputCol; label: string; color: string }[] = [
  { key: "T_0.2m_C", label: "T 0.2 m", color: "#ffb020" },
  { key: "T_0.6m_C", label: "T 0.6 m", color: "#ff7a3d" },
  { key: "T_1m_C", label: "T 1.0 m", color: "#ff4d3d" },
  { key: "X_overall_pct", label: "Conversion", color: "#4ade80" },
  { key: "P_out_bar_g", label: "Pressure", color: "#4da3ff" },
  { key: "Q_total_kW", label: "Heat duty", color: "#a78bfa" },
];

const TITLES: Record<ModelKind, string> = {
  physics: "Physics",
  serial: "Serial Hybrid",
  parallel: "Parallel Hybrid",
  pinn: "PINN",
};

function fmtR2(n: number) {
  if (Math.abs(n) >= 10) return n.toFixed(1);
  if (n > 0.999) return n.toFixed(4);
  return n.toFixed(3);
}

export default function R2Charts({
  info,
  selected,
  onSelect,
}: {
  info: BackendInfo;
  selected: ModelKind;
  onSelect: (m: ModelKind) => void;
}) {
  return (
    <section className="panel model-hist">
      <div className="panel-head">
        <h3>R² per model</h3>
        <p>
          Each bar is that model&apos;s R². The scale runs from 0 to 1, and 1 is a perfect fit. The number above the
          bar is the actual R². A negative R² means the model fits worse than the average of the data.
        </p>
      </div>

      <div className="mh-grid" style={{ "--mh-cols": BARS.length } as CSSProperties}>
        {MODEL_ORDER.map((id) => (
          <article
            key={id}
            className={`mh-card ${id} ${id === selected ? "active" : ""}`}
            onClick={() => onSelect(id)}
          >
            <header>
              <i aria-hidden />
              <h4>{TITLES[id]}</h4>
            </header>

            <div className="mh-plot">
              <div className="mh-axis" aria-hidden>
                <span>1</span>
                <span>0.5</span>
                <span>0</span>
              </div>
              <div className="mh-bars">
                {BARS.map((bar) => {
                  const r2 = info.models[id].test[bar.key].r2;
                  const pct = Math.min(Math.max(r2, 0), 1) * 100;
                  return (
                    <div
                      key={bar.key}
                      className={`mh-col ${r2 < 0 ? "outside" : ""}`}
                      style={{ "--vc": bar.color } as CSSProperties}
                      title={`${bar.label}: R² ${fmtR2(r2)}`}
                    >
                      <span className="mh-value">{fmtR2(r2)}</span>
                      <span className="mh-track">
                        {pct > 0 && <span className="mh-bar" style={{ height: `${Math.max(pct, 1.5)}%` }} />}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="mh-labels">
              {BARS.map((bar) => (
                <span key={bar.key} style={{ "--vc": bar.color } as CSSProperties}>
                  {bar.label}
                  <small>R²</small>
                </span>
              ))}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
