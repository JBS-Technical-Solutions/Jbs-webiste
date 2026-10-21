"use client";

import { useEffect, useState } from "react";
import Logo from "../Logo";
import ModelHistograms, { type HistogramVariable } from "../hx/ModelHistograms";
import R2Charts from "./R2Charts";
import ReactorDiagram from "./ReactorDiagram";
import ReactorGeometry from "../meoh/ReactorGeometry";
import {
  BACKEND_OFFLINE,
  type BackendInfo,
  DEFAULT_INPUTS,
  MODEL_ORDER,
  type ModelKind,
  PROFILE_KEYS,
  type TwinInputs,
  type TwinOutput,
  compareModels,
  fetchInfo,
} from "./api";
import "../hx/hx.css";
import "../meoh/meoh.css";

const MODELS: Record<ModelKind, { title: string; blurb: string }> = {
  physics: { title: "Physics", blurb: "LHHW kinetics → plug-flow ODEs → axial profile" },
  serial: { title: "Serial Hybrid", blurb: "Physics ODEs with a learned reaction rate" },
  parallel: { title: "Parallel Hybrid", blurb: "Physics baseline plus an ML residual" },
  pinn: { title: "PINN", blurb: "Physics-Informed Neural Network" },
};

const histogramVariables = (info: BackendInfo | null): HistogramVariable<TwinOutput>[] => [
  {
    key: "T_out",
    label: "Outlet T",
    unit: "°C",
    color: "#ff7a3d",
    value: (r) => r.outputs?.T_10,
    range: info?.output_ranges?.["T_1m_C"],
  },
  {
    key: "X",
    label: "Conversion",
    unit: "%",
    color: "#4ade80",
    value: (r) => r.outputs?.X_pct,
    range: info?.output_ranges?.X_overall_pct,
  },
  {
    key: "P_out",
    label: "Outlet P",
    unit: "bar_g",
    color: "#4da3ff",
    value: (r) => r.outputs?.P_out_bar_g,
    range: info?.output_ranges?.P_out_bar_g,
  },
  {
    key: "Q",
    label: "Heat duty",
    unit: "kW",
    color: "#a78bfa",
    // Bar scale uses magnitude; labels show heat duty as negative (heat into the bed).
    value: (r) => (r.outputs?.Q_kW != null ? Math.abs(r.outputs.Q_kW) : null),
    format: (n) => `-${n.toLocaleString(undefined, { maximumFractionDigits: 1, minimumFractionDigits: 1 })}`,
    formatFullScale: (max) =>
      `-${max.toLocaleString(undefined, { maximumFractionDigits: 1, minimumFractionDigits: 1 })}`,
    range: info?.output_ranges?.Q_total_kW,
  },
];

function duty(n: number | null | undefined, digits = 2) {
  if (n == null || !Number.isFinite(n)) return "—";
  const shown = -Math.abs(n);
  return shown.toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}

type Status = "checking" | "online" | "offline";

function fmt(n: number | null | undefined, digits = 2) {
  if (n == null || !Number.isFinite(n)) return "—";
  return n.toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}

export default function MethanolHeatingTwin({ className = "" }: { className?: string }) {
  const [model, setModel] = useState<ModelKind>("parallel");
  const [inputs, setInputs] = useState<TwinInputs>(DEFAULT_INPUTS);
  const [ranInputs, setRanInputs] = useState<TwinInputs | null>(null);
  const [results, setResults] = useState<TwinOutput[] | null>(null);
  const [info, setInfo] = useState<BackendInfo | null>(null);
  const [status, setStatus] = useState<Status>("checking");
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [flash, setFlash] = useState(0);

  const run = async (nextInputs = inputs) => {
    setRunning(true);
    setError(null);
    try {
      const out = await compareModels(nextInputs);
      setResults(out);
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
  const T_heat = ranInputs?.T_heat_C ?? inputs.T_heat_C;
  const rx = info?.reactor;

  const update = (key: keyof TwinInputs, raw: string) => {
    setInputs((prev) => ({ ...prev, [key]: Number(raw) }));
  };

  return (
    <div className={`hx-app meoh-app ${className}`}>
      <div className="atmosphere" aria-hidden />
      <div className="grid-glow" aria-hidden />

      <header className="topbar">
        <span />
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
          <p className="eyebrow">Methanol Heating Media</p>
          <h2 className="hero-title">
            Set the heat media.
            <br />
            <em>Watch the bed respond.</em>
          </h2>
          <p className="lede">
            Same packed-bed methanol decomposition, CH₃OH → CO + 2H₂, but heating-media temperature is a live
            plant input — not fixed. Four engines — LHHW physics, serial and parallel hybrids, and a
            physics-informed neural network — predict the axial temperature profile, conversion, pressure drop
            and heat duty from the Python models.
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
              <p>Temperatures in °C · pressure in bar_g · flow in kgmole/h</p>
            </div>

            <label className="field">
              <span>Inlet temperature</span>
              <div className="field-row">
                <input
                  type="number"
                  step="any"
                  min="0"
                  max="1000"
                  value={inputs.T_in_C}
                  onChange={(e) => update("T_in_C", e.target.value)}
                />
                <em>°C</em>
              </div>
            </label>

            <label className="field">
              <span>Inlet pressure</span>
              <div className="field-row">
                <input
                  type="number"
                  step="any"
                  min="0"
                  max="50"
                  value={inputs.P_in_bar_g}
                  onChange={(e) => update("P_in_bar_g", e.target.value)}
                />
                <em>bar_g</em>
              </div>
            </label>

            <label className="field">
              <span>Heating media temp</span>
              <div className="field-row">
                <input
                  type="number"
                  step="any"
                  min="0"
                  max="1000"
                  value={inputs.T_heat_C}
                  onChange={(e) => update("T_heat_C", e.target.value)}
                />
                <em>°C</em>
              </div>
            </label>

            <label className="field">
              <span>Methanol flow</span>
              <div className="field-row">
                <input
                  type="number"
                  step="any"
                  min="0"
                  max="50"
                  value={inputs.F_in_kgmole_h}
                  onChange={(e) => update("F_in_kgmole_h", e.target.value)}
                />
                <em>kgmole/h</em>
              </div>
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
            </div>

            <ReactorDiagram
              T_in={ranInputs?.T_in_C}
              P_in={ranInputs?.P_in_bar_g}
              F_in={ranInputs?.F_in_kgmole_h}
              T_out={out?.T_10}
              P_out={out?.P_out_bar_g}
              X_pct={out?.X_pct}
              Q_kW={out?.Q_kW != null ? -Math.abs(out.Q_kW) : undefined}
              profile={PROFILE_KEYS.map((k) => out?.[k])}
              T_heat={T_heat}
              animate={out != null}
            />

            {result?.error && (
              <div className="banner error compact" role="alert">
                {result.error}
              </div>
            )}

            {rx && (
              <ReactorGeometry
                reactor={rx}
                T_heat={T_heat}
                note="tube and bed fixed · heat media is your set point"
              />
            )}

            {result && result.warnings.length > 0 && (
              <ul className="banner warn">
                {result.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            )}

          </section>
        </div>

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
                    <th>T out (°C)</th>
                    <th>Conversion (%)</th>
                    <th>P out (bar_g)</th>
                    <th>Duty (kW)</th>
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
                      <td>{fmt(r.outputs?.T_10)}</td>
                      <td>{fmt(r.outputs?.X_pct)}</td>
                      <td>{fmt(r.outputs?.P_out_bar_g, 3)}</td>
                      <td>{duty(r.outputs?.Q_kW)}</td>
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
              physics: MODELS.physics.title,
              serial: MODELS.serial.title,
              parallel: MODELS.parallel.title,
              pinn: MODELS.pinn.title,
            }}
            onSelect={setModel}
            showFullScale
          />
        )}

        {results && info && <R2Charts info={info} selected={model} onSelect={setModel} />}
      </div>
    </div>
  );
}
