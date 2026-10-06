"use client";

import { useEffect, useState } from "react";
import Logo from "../Logo";
import ExchangerDiagram from "./ExchangerDiagram";
import ModelHistograms, { type HistogramVariable } from "./ModelHistograms";
import {
  BACKEND_OFFLINE,
  type BackendInfo,
  DEFAULT_INPUTS,
  MODEL_ORDER,
  type ModelKind,
  type TwinInputs,
  type TwinOutput,
  compareModels,
  fetchInfo,
} from "./api";
import "./hx.css";

const MODELS: Record<ModelKind, { title: string; blurb: string }> = {
  physics: { title: "Physics", blurb: "Kern Method → HTCs → Overall U → NTU Method → Outlet Temps" },
  serial: { title: "Serial Hybrid", blurb: "ML predicts U, physics rates outlets" },
  parallel: { title: "Parallel Hybrid", blurb: "Physics + ML residual corrections" },
  pinn: { title: "PINN", blurb: "Physics-Informed Neural Network" },
};

const histogramVariables = (info: BackendInfo | null): HistogramVariable<TwinOutput>[] => [
  { key: "U", label: "U", unit: "W/m²·K", color: "#a78bfa", value: (r) => r.U, range: info?.output_ranges?.U },
  {
    key: "T_air_out",
    label: "Hot fluid out",
    unit: "°C",
    color: "#ff7a3d",
    value: (r) => r.T_air_out,
    range: info?.output_ranges?.T_air_out,
  },
  {
    key: "T_water_out",
    label: "Cold fluid out",
    unit: "°C",
    color: "#4da3ff",
    value: (r) => r.T_water_out,
    range: info?.output_ranges?.T_water_out,
  },
  { key: "Q_kW", label: "Duty", unit: "kW", color: "#4ade80", value: (r) => r.Q_kW, range: info?.output_ranges?.Q_kW },
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

export default function HeatExchangerTwin({ className = "" }: { className?: string }) {
  const [model, setModel] = useState<ModelKind>("serial");
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
  const deltaAir = result && ranInputs ? ranInputs.T_air_in - result.T_air_out : 0;
  const deltaWater = result && ranInputs ? result.T_water_out - ranInputs.T_water_in : 0;

  const update = (key: keyof TwinInputs, raw: string) => {
    setInputs((prev) => ({ ...prev, [key]: Number(raw) }));
  };

  const range = (key: keyof TwinInputs) => {
    const r = info?.training_ranges[key];
    return r ? `trained ${fmt(r.min, 0)} – ${fmt(r.max, 0)}` : null;
  };

  return (
    <div className={`hx-app ${className}`}>
      <div className="atmosphere" aria-hidden />
      <div className="grid-glow" aria-hidden />

      <header className="topbar">
        <span className="pill muted">
          TEMA Type A · {info?.geometry.N_tubes ?? 160} tubes · L {info?.geometry.L_m ?? 6} m
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
          <p className="eyebrow">Heat Exchanger Model</p>
          <h2 className="hero-title">
            Rate the exchanger.
            <br />
            <em>See the twin respond.</em>
          </h2>
          <p className="lede">
            Four engines — physics E-NTU, serial ML→physics, parallel residuals, and a physics-informed neural
            network — served live from the Python backend on the same shell-side hot fluid / tube-side cold fluid duty.
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
              <p>Mass flows in kg/h · temperatures in °C</p>
            </div>

            <label className="field">
              <span>Hot Fluid (shell)</span>
              <div className="field-row">
                <input
                  type="number"
                  step="100"
                  min="100"
                  value={inputs.m_air_kgh}
                  onChange={(e) => update("m_air_kgh", e.target.value)}
                />
                <em>kg/h</em>
              </div>
              {range("m_air_kgh") && <small className="field-hint">{range("m_air_kgh")}</small>}
            </label>

            <label className="field">
              <span>Cold Fluid (tubes)</span>
              <div className="field-row">
                <input
                  type="number"
                  step="100"
                  min="100"
                  value={inputs.m_water_kgh}
                  onChange={(e) => update("m_water_kgh", e.target.value)}
                />
                <em>kg/h</em>
              </div>
              {range("m_water_kgh") && <small className="field-hint">{range("m_water_kgh")}</small>}
            </label>

            <label className="field">
              <span>Hot fluid inlet temperature</span>
              <div className="field-row">
                <input
                  type="number"
                  step="1"
                  value={inputs.T_air_in}
                  onChange={(e) => update("T_air_in", e.target.value)}
                />
                <em>°C</em>
              </div>
              {range("T_air_in") && <small className="field-hint">{range("T_air_in")}</small>}
            </label>

            <label className="field">
              <span>Cold fluid inlet temperature</span>
              <div className="field-row">
                <input
                  type="number"
                  step="1"
                  min="1"
                  max="99"
                  value={inputs.T_water_in}
                  onChange={(e) => update("T_water_in", e.target.value)}
                />
                <em>°C</em>
              </div>
              {range("T_water_in") && <small className="field-hint">{range("T_water_in")}</small>}
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

            <ExchangerDiagram
              T_air_in={ranInputs?.T_air_in}
              T_air_out={result?.T_air_out}
              T_water_in={ranInputs?.T_water_in}
              T_water_out={result?.T_water_out}
              animate={result != null}
            />

            <div className="metrics">
              <article className="metric hero-metric">
                <span>Overall U</span>
                <strong>{fmt(result?.U)}</strong>
                <em>W/m²·K</em>
              </article>
              <article className="metric">
                <span>Hot fluid outlet</span>
                <strong>{fmt(result?.T_air_out)}</strong>
                <em>°C · Δ {fmt(deltaAir)}°</em>
              </article>
              <article className="metric">
                <span>Cold fluid outlet</span>
                <strong>{fmt(result?.T_water_out)}</strong>
                <em>°C · Δ +{fmt(deltaWater)}°</em>
              </article>
              <article className="metric">
                <span>Duty</span>
                <strong>{fmt(result?.Q_kW)}</strong>
                <em>kW</em>
              </article>
              <article className="metric">
                <span>NTU</span>
                <strong>{fmt(result?.NTU, 3)}</strong>
                <em>dimensionless</em>
              </article>
              <article className="metric">
                <span>Effectiveness</span>
                <strong>{fmt(result ? result.epsilon * 100 : null, 1)}</strong>
                <em>%</em>
              </article>
            </div>

            {result?.physics_ref && (
              <p className="phys-ref">
                vs pure physics: U {signed(result.U - result.physics_ref.U)} W/m²·K · Hot fluid out{" "}
                {signed(result.T_air_out - result.physics_ref.T_air_out)}° · Cold fluid out{" "}
                {signed(result.T_water_out - result.physics_ref.T_water_out)}°
              </p>
            )}

            {result && (
              <div className="hydraulics">
                <p className="hydraulics-head">
                  Inlet pressures, film coefficients &amp; pressure drop
                  {result.model !== "physics" && <em> · from A0 physics rating at these inputs</em>}
                </p>
                <dl>
                  <div>
                    <dt>P inlet (cold fluid)</dt>
                    <dd>{fmt(result.hydraulics.P_water_in_kPa, 1)} <small>kPa</small></dd>
                  </div>
                  <div>
                    <dt>P inlet (hot fluid)</dt>
                    <dd>{fmt(result.hydraulics.P_air_in_kPa, 1)} <small>kPa</small></dd>
                  </div>
                  <div>
                    <dt>h inside (cold fluid)</dt>
                    <dd>{fmt(result.hydraulics.h_i, 1)} <small>W/m²·K</small></dd>
                  </div>
                  <div>
                    <dt>h outside (hot fluid)</dt>
                    <dd>{fmt(result.hydraulics.h_o, 1)} <small>W/m²·K</small></dd>
                  </div>
                  <div>
                    <dt>ΔP tube (cold fluid)</dt>
                    <dd>{fmt(result.hydraulics.dP_tube_kPa, 3)} <small>kPa</small></dd>
                  </div>
                  <div>
                    <dt>ΔP shell (hot fluid)</dt>
                    <dd>{fmt(result.hydraulics.dP_shell_kPa, 3)} <small>kPa</small></dd>
                  </div>
                  <div>
                    <dt>Re tube (cold fluid)</dt>
                    <dd>{fmt(result.hydraulics.Re_tube, 0)}</dd>
                  </div>
                  <div>
                    <dt>Re shell (hot fluid)</dt>
                    <dd>{fmt(result.hydraulics.Re_shell, 0)}</dd>
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
              <span>Aₒ = {fmt(result?.A_o_total, 3)} m²</span>
              <span>
                {result?.iterations != null ? `Converged in ${result.iterations} iter` : "Direct NN inference"}
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
                    <th>U (W/m²·K)</th>
                    <th>Hot fluid out (°C)</th>
                    <th>Cold fluid out (°C)</th>
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
                      <td>{fmt(r.U)}</td>
                      <td>{fmt(r.T_air_out)}</td>
                      <td>{fmt(r.T_water_out)}</td>
                      <td>{fmt(r.Q_kW)}</td>
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
