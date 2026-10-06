"use client";

import { useEffect, useState } from "react";
import Logo from "../Logo";
import ModelHistograms, { type HistogramVariable } from "../hx/ModelHistograms";
import PumpCurve from "./PumpCurve";
import PumpDiagram from "./PumpDiagram";
import {
  BACKEND_OFFLINE,
  type BackendInfo,
  DEFAULT_INPUTS,
  MODEL_ORDER,
  type ModelCurve,
  type ModelKind,
  type TwinInputs,
  type TwinOutput,
  compareModels,
  fetchCurve,
  fetchInfo,
} from "./api";
import "../hx/hx.css";
import "./pump.css";

const MODELS: Record<ModelKind, { title: string; blurb: string; color: string }> = {
  serial: { title: "Serial Hybrid", blurb: "Physics P_hyd → ML efficiency → P_hyd / η", color: "#3ecfcf" },
  parallel: { title: "Parallel Hybrid", blurb: "First-principles power + ML residual", color: "#f0c75e" },
  pinn: { title: "PINN", blurb: "Physics-Informed Neural Network", color: "#ff6a3d" },
};

const G = 9.80665;

const scaled = (r: { min: number; max: number } | undefined, k: number) =>
  r ? { min: r.min * k, max: r.max * k } : undefined;

const histogramVariables = (info: BackendInfo | null): HistogramVariable<TwinOutput>[] => [
  {
    key: "brake",
    label: "Brake power",
    unit: "kW",
    color: "#ffb347",
    value: (r) => r.outputs?.brake_kW,
    range: info?.output_ranges?.brake_kW,
  },
  {
    key: "hydraulic",
    label: "Hydraulic power",
    unit: "kW",
    color: "#4ade80",
    value: (r) => r.outputs?.hydraulic_kW,
    range: info?.output_ranges?.hydraulic_kW,
  },
  {
    key: "eff",
    label: "Efficiency",
    unit: "%",
    color: "#a78bfa",
    value: (r) => (r.outputs ? r.outputs.efficiency * 100 : null),
    range: scaled(info?.output_ranges?.efficiency, 100),
  },
];

type Status = "checking" | "online" | "offline";

function fmt(n: number | null | undefined, digits = 2) {
  if (n == null || !Number.isFinite(n)) return "—";
  return n.toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}

function signed(n: number, digits = 2) {
  return `${n >= 0 ? "+" : ""}${fmt(n, digits)}`;
}

export default function PumpTwin({ className = "" }: { className?: string }) {
  const [model, setModel] = useState<ModelKind>("serial");
  const [inputs, setInputs] = useState<TwinInputs>(DEFAULT_INPUTS);
  const [ranInputs, setRanInputs] = useState<TwinInputs | null>(null);
  const [results, setResults] = useState<TwinOutput[] | null>(null);
  const [curves, setCurves] = useState<ModelCurve[] | null>(null);
  const [info, setInfo] = useState<BackendInfo | null>(null);
  const [status, setStatus] = useState<Status>("checking");
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [flash, setFlash] = useState(0);

  const run = async (nextInputs = inputs) => {
    setRunning(true);
    setError(null);
    try {
      const [out, curve] = await Promise.all([compareModels(nextInputs), fetchCurve(nextInputs)]);
      setResults(out);
      setCurves(curve);
      setRanInputs(nextInputs);
      setStatus("online");
      setFlash((f) => f + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      if (e instanceof Error && e.message.startsWith(BACKEND_OFFLINE)) setStatus("offline");
    } finally {
      setRunning(false);
    }
  };

  const load = () =>
    fetchInfo()
      .then((next) => {
        setInfo(next);
        setStatus("online");
        return run();
      })
      .catch((e) => {
        setStatus("offline");
        setError(e instanceof Error ? e.message : String(e));
      });

  const connect = () => {
    setStatus("checking");
    load();
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const result = results?.find((r) => r.model === model) ?? null;
  const out = result?.outputs ?? null;
  const dP = ranInputs ? ranInputs.P_out_bar - ranInputs.P_in_bar : null;
  const head = ranInputs && dP != null ? (dP * 1e5) / (ranInputs.rho * G) : null;
  const volumeFlow = ranInputs ? ranInputs.flow_kgh / ranInputs.rho : null;
  const specificEnergy = out && volumeFlow ? out.brake_kW / volumeFlow : null;

  const update = (key: keyof TwinInputs, raw: string) => {
    setInputs((prev) => ({ ...prev, [key]: Number(raw) }));
  };

  const range = (key: keyof TwinInputs, digits: number) => {
    const r = info?.training_ranges[key];
    if (!r) return null;
    return r.min === r.max ? `fixed at ${fmt(r.min, digits)} in the data` : `data range ${fmt(r.min, digits)} – ${fmt(r.max, digits)}`;
  };

  return (
    <div className={`hx-app pump-app ${className}`}>
      <div className="atmosphere" aria-hidden />
      <div className="grid-glow" aria-hidden />

      <header className="topbar">
        <span className="pill muted">Centrifugal pump · water service</span>
        <Logo className="topbar-logo" inverse />
        <div className="top-meta">
          <span className={`pill status ${status}`}>
            <i aria-hidden />
            {status === "online" ? "Python models online" : status === "checking" ? "Connecting…" : "Backend offline"}
          </span>
        </div>
      </header>

      <div className="stage">
        <section className="hero-copy">
          <p className="eyebrow">Water Pump Model</p>
          <h2 className="hero-title">
            Set the duty.
            <br />
            <em>See the shaft power.</em>
          </h2>
          <p className="lede">
            Three engines — a serial hybrid (physics hydraulic power with an ML efficiency), a parallel hybrid
            (first-principles power with an ML residual correction) and a physics-informed neural network — predict
            the pump&apos;s brake power and efficiency live from the Python backend.
          </p>
        </section>

        {status === "offline" && (
          <div className="banner error" role="alert">
            <strong>The simulation models are offline.</strong>
            <span>They may still be starting up. Please retry in a moment.</span>
            <button type="button" className="preset" onClick={connect}>
              Retry connection
            </button>
          </div>
        )}

        <section className="model-rail" aria-label="Model selection">
          {MODEL_ORDER.map((id) => (
            <button
              key={id}
              type="button"
              className={`model-chip ${model === id ? "active" : ""}`}
              aria-pressed={model === id}
              onClick={() => setModel(id)}
            >
              <span className="chip-title">{MODELS[id].title}</span>
              <span className="chip-blurb">{MODELS[id].blurb}</span>
            </button>
          ))}
        </section>

        <div className="workspace">
          <form
            className="panel inputs"
            onSubmit={(e) => {
              e.preventDefault();
              run(inputs);
            }}
          >
            <div className="panel-head">
              <h3>Operating inputs</h3>
              <p>Mass flow in kg/h · pressures in bar · density in kg/m³</p>
            </div>

            <label className="field">
              <span>Water flow</span>
              <div className="field-row">
                <input
                  type="number"
                  step="500"
                  min="1"
                  value={inputs.flow_kgh}
                  onChange={(e) => update("flow_kgh", e.target.value)}
                />
                <em>kg/h</em>
              </div>
              {range("flow_kgh", 0) && <small className="field-hint">{range("flow_kgh", 0)}</small>}
            </label>

            <label className="field">
              <span>Inlet (suction) pressure</span>
              <div className="field-row">
                <input
                  type="number"
                  step="0.001"
                  min="0"
                  value={inputs.P_in_bar}
                  onChange={(e) => update("P_in_bar", e.target.value)}
                />
                <em>bar</em>
              </div>
              {range("P_in_bar", 3) && <small className="field-hint">{range("P_in_bar", 3)}</small>}
            </label>

            <label className="field">
              <span>Outlet (discharge) pressure</span>
              <div className="field-row">
                <input
                  type="number"
                  step="5"
                  min="0"
                  value={inputs.P_out_bar}
                  onChange={(e) => update("P_out_bar", e.target.value)}
                />
                <em>bar</em>
              </div>
              {range("P_out_bar", 0) && <small className="field-hint">{range("P_out_bar", 0)}</small>}
            </label>

            <label className="field">
              <span>Water density</span>
              <div className="field-row">
                <input
                  type="number"
                  step="0.1"
                  min="1"
                  value={inputs.rho}
                  onChange={(e) => update("rho", e.target.value)}
                />
                <em>kg/m³</em>
              </div>
              {range("rho", 1) && <small className="field-hint">{range("rho", 1)}</small>}
            </label>

            {error && status !== "offline" && (
              <div className="banner error compact" role="alert">
                {error}
              </div>
            )}

            <button type="submit" className="cta" disabled={running || status === "offline"}>
              {running ? "Computing…" : "Run digital twin"}
            </button>
          </form>

          <section className="panel results" key={flash}>
            <div className="panel-head">
              <h3>{result?.modelLabel ?? "Outputs"}</h3>
              <p>{result?.approach ?? "Run the twin to see model outputs."}</p>
              {result && <span className="source-tag">Source: {result.source}</span>}
            </div>

            <PumpDiagram
              flow={ranInputs?.flow_kgh}
              P_in={ranInputs?.P_in_bar}
              P_out={ranInputs?.P_out_bar}
              brake={out?.brake_kW}
              hydraulic={out?.hydraulic_kW}
              animate={out != null}
            />

            {result?.error && (
              <div className="banner error compact" role="alert">
                {result.error}
              </div>
            )}

            <div className="metrics">
              <article className="metric hero-metric">
                <span>Brake power</span>
                <strong>{fmt(out?.brake_kW)}</strong>
                <em>kW at the shaft</em>
              </article>
              <article className="metric">
                <span>Hydraulic power</span>
                <strong>{fmt(out?.hydraulic_kW)}</strong>
                <em>kW · Q × ΔP</em>
              </article>
              <article className="metric">
                <span>Pump efficiency</span>
                <strong>{fmt(out ? out.efficiency * 100 : null, 2)}</strong>
                <em>%</em>
              </article>
              <article className="metric">
                <span>Differential pressure</span>
                <strong>{fmt(dP, 2)}</strong>
                <em>bar</em>
              </article>
              <article className="metric">
                <span>Differential head</span>
                <strong>{fmt(head, 0)}</strong>
                <em>m of water</em>
              </article>
              <article className="metric">
                <span>Specific energy</span>
                <strong>{fmt(specificEnergy, 3)}</strong>
                <em>kWh/m³ pumped</em>
              </article>
            </div>

            {out?.physics_brake_kW != null && out.residual_kW != null && (
              <p className="phys-ref">
                First-principles brake power {fmt(out.physics_brake_kW, 3)} kW · ML residual correction{" "}
                {signed(out.residual_kW, 4)} kW
              </p>
            )}

            {result && result.warnings.length > 0 && (
              <ul className="banner warn">
                {result.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            )}

            <footer className="result-foot">
              <span>Volumetric flow {fmt(volumeFlow, 2)} m³/h</span>
              <span>Trained on {info?.rows ?? "—"} operating points</span>
            </footer>
          </section>
        </div>

        {curves && (
          <PumpCurve
            series={curves.map((c) => ({
              model: c.model,
              label: MODELS[c.model].title,
              color: MODELS[c.model].color,
              points: c.points,
            }))}
            selected={model}
            onSelect={setModel}
            operating={out && ranInputs ? { flow_kgh: ranInputs.flow_kgh, brake_kW: out.brake_kW } : null}
          />
        )}

        {results && (
          <section className="panel compare">
            <div className="panel-head">
              <h3>All models at these inputs</h3>
              <p>Click a row to show that model in the outputs panel.</p>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Brake power (kW)</th>
                    <th>Hydraulic power (kW)</th>
                    <th>Efficiency (%)</th>
                    <th>Test R²</th>
                    <th>Test MAE (kW)</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((r) => (
                    <tr
                      key={r.model}
                      className={r.model === model ? "active" : ""}
                      onClick={() => setModel(r.model)}
                    >
                      <td>{MODELS[r.model].title}</td>
                      <td>{fmt(r.outputs?.brake_kW, 3)}</td>
                      <td>{fmt(r.outputs?.hydraulic_kW, 3)}</td>
                      <td>{fmt(r.outputs ? r.outputs.efficiency * 100 : null, 3)}</td>
                      <td>{fmt(info?.models[r.model].test.r2, 5)}</td>
                      <td>{fmt(info?.models[r.model].test.mae, 3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {results && (
          <ModelHistograms
            results={results}
            variables={histogramVariables(info)}
            selected={model}
            titles={{
              serial: MODELS.serial.title,
              parallel: MODELS.parallel.title,
              pinn: MODELS.pinn.title,
            }}
            onSelect={setModel}
          />
        )}
      </div>
    </div>
  );
}
