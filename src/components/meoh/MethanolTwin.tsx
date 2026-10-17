"use client";

import { useEffect, useState } from "react";
import Logo from "../Logo";
import ModelHistograms, { type HistogramVariable } from "../hx/ModelHistograms";
import ReactorDiagram from "./ReactorDiagram";
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
import "./meoh.css";

const MODELS: Record<ModelKind, { title: string; blurb: string }> = {
  physics: { title: "Physics", blurb: "LHHW kinetics → plug-flow ODEs → axial profile" },
  serial: { title: "Serial Hybrid", blurb: "Physics ODEs with a learned reaction rate" },
  parallel: { title: "Parallel Hybrid", blurb: "Physics baseline plus an ML residual" },
  pinn: { title: "PINN", blurb: "Physics-Informed Neural Network" },
};

const T_HEAT_DEFAULT = 275;

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
    value: (r) => r.outputs?.Q_kW,
    range: info?.output_ranges?.Q_total_kW,
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

const h2Produced = (r: TwinOutput | null, inputs: TwinInputs | null) =>
  r?.outputs && inputs ? 2 * inputs.F_in_kgmole_h * 1000 * (r.outputs.X_pct / 100) : null;

export default function MethanolTwin({ className = "" }: { className?: string }) {
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
  const ref = result?.physics_ref ?? null;
  const T_heat = info?.reactor.T_heat_C ?? T_HEAT_DEFAULT;
  const dP = out && ranInputs ? ranInputs.P_in_bar_g - out.P_out_bar_g : null;
  const rx = info?.reactor;
  const bedArea = rx ? (Math.PI * rx.D_m * rx.D_m) / 4 : null;
  const bedVolume = bedArea != null && rx ? bedArea * rx.L_m : null;
  const specificSurface = rx ? (6 * (1 - rx.epsilon)) / rx.dp_m : null;

  const update = (key: keyof TwinInputs, raw: string) => {
    setInputs((prev) => ({ ...prev, [key]: Number(raw) }));
  };

  const limit = (max: number, digits = 0) => `0 – ${fmt(max, digits)}`;

  return (
    <div className={`hx-app meoh-app ${className}`}>
      <div className="atmosphere" aria-hidden />
      <div className="grid-glow" aria-hidden />

      <header className="topbar">
        <span className="pill muted">
          Packed bed · D {info?.reactor.D_m ?? 0.1} m · L {info?.reactor.L_m ?? 1} m
        </span>
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
          <p className="eyebrow">Methanol Reformer Model</p>
          <h2 className="hero-title">
            Feed the reactor.
            <br />
            <em>Watch the bed respond.</em>
          </h2>
          <p className="lede">
            Methanol decomposition, CH₃OH → CO + 2H₂, in a jacket-heated packed-bed tube. Four engines — LHHW
            physics, serial and parallel hybrids, and a physics-informed neural network — predict the axial
            temperature profile, conversion, pressure drop and heat duty live from the Python backend.
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
              <p>Temperature in °C · pressure in bar_g · flow in kgmole/h</p>
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
              <small className="field-hint">{limit(1000)}</small>
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
              <small className="field-hint">{limit(50, 0)}</small>
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
              <small className="field-hint">{limit(50)}</small>
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

            <ReactorDiagram
              T_in={ranInputs?.T_in_C}
              P_in={ranInputs?.P_in_bar_g}
              profile={PROFILE_KEYS.map((k) => out?.[k])}
              P_out={out?.P_out_bar_g}
              T_heat={T_heat}
              animate={out != null}
            />

            {result?.error && (
              <div className="banner error compact" role="alert">
                {result.error}
              </div>
            )}

            <div className="metrics">
              <article className="metric hero-metric">
                <span>Outlet temperature</span>
                <strong>{fmt(out?.T_10)}</strong>
                <em>°C</em>
              </article>
              <article className="metric">
                <span>Conversion</span>
                <strong>{fmt(out?.X_pct, 2)}</strong>
                <em>%</em>
              </article>
              <article className="metric">
                <span>H₂ produced</span>
                <strong>{fmt(h2Produced(result, ranInputs), 1)}</strong>
                <em>mol/h</em>
              </article>
              <article className="metric">
                <span>Duty</span>
                <strong>{fmt(out?.Q_kW)}</strong>
                <em>kW</em>
              </article>
              <article className="metric">
                <span>Outlet pressure</span>
                <strong>{fmt(out?.P_out_bar_g, 3)}</strong>
                <em>bar_g</em>
              </article>
              <article className="metric">
                <span>Pressure drop</span>
                <strong>{fmt(dP != null ? dP * 1000 : null, 1)}</strong>
                <em>mbar</em>
              </article>
            </div>

            {out && ref && (
              <p className="phys-ref">
                vs calibrated physics{result?.eta != null ? ` (η ${result.eta.toExponential(3)})` : ""}: T out{" "}
                {signed(out.T_10 - ref.T_10)}° · conversion {signed(out.X_pct - ref.X_pct, 3)} pts · P out{" "}
                {signed(out.P_out_bar_g - ref.P_out_bar_g, 3)} bar · duty {signed(out.Q_kW - ref.Q_kW, 3)} kW
              </p>
            )}

            {rx && (
              <div className="hydraulics">
                <p className="hydraulics-head">
                  Reactor geometry
                  <em> · constant for every operating point</em>
                </p>
                <dl>
                  <div>
                    <dt>Tube diameter</dt>
                    <dd>{fmt(rx.D_m, 2)} <small>m</small></dd>
                  </div>
                  <div>
                    <dt>Bed length</dt>
                    <dd>{fmt(rx.L_m, 1)} <small>m</small></dd>
                  </div>
                  <div>
                    <dt>Particle diameter</dt>
                    <dd>{fmt(rx.dp_m * 1000, 1)} <small>mm</small></dd>
                  </div>
                  <div>
                    <dt>Bed voidage</dt>
                    <dd>{fmt(rx.epsilon, 2)}</dd>
                  </div>
                  <div>
                    <dt>Cross section</dt>
                    <dd>{fmt(bedArea, 4)} <small>m²</small></dd>
                  </div>
                  <div>
                    <dt>Bed volume</dt>
                    <dd>{fmt(bedVolume, 4)} <small>m³</small></dd>
                  </div>
                  <div>
                    <dt>Specific surface</dt>
                    <dd>{fmt(specificSurface, 0)} <small>1/m</small></dd>
                  </div>
                  <div>
                    <dt>Jacket-side HTC</dt>
                    <dd>{fmt(rx.h_heat_W_m2K, 0)} <small>W/m²·K</small></dd>
                  </div>
                </dl>
              </div>
            )}

            {result && result.warnings.length > 0 && (
              <ul className="banner warn">
                {result.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            )}

            <footer className="result-foot">
              <span>CH₃OH → CO + 2H₂</span>
              <span>
                D {fmt(info?.reactor.D_m ?? 0.1, 2)} m · L {fmt(info?.reactor.L_m ?? 1, 1)} m
              </span>
            </footer>
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
                      <td>{fmt(r.outputs?.Q_kW)}</td>
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
          />
        )}
      </div>
    </div>
  );
}
