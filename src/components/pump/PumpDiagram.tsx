"use client";

import type { CSSProperties } from "react";

type Props = {
  flow?: number;
  P_in?: number;
  P_out?: number;
  brake?: number;
  hydraulic?: number;
  animate: boolean;
};

const STOPS: [number, [number, number, number]][] = [
  [0, [62, 207, 207]],
  [50, [77, 163, 255]],
  [150, [167, 139, 250]],
  [300, [255, 122, 61]],
];

function pressureColor(p: number | undefined) {
  if (p == null || !Number.isFinite(p)) return "rgb(120, 140, 160)";
  if (p <= STOPS[0][0]) return `rgb(${STOPS[0][1].join(",")})`;
  for (let i = 1; i < STOPS.length; i++) {
    const [p1, c1] = STOPS[i];
    if (p <= p1) {
      const [p0, c0] = STOPS[i - 1];
      const k = (p - p0) / (p1 - p0);
      return `rgb(${c0.map((c, j) => Math.round(c + (c1[j] - c) * k)).join(",")})`;
    }
  }
  return `rgb(${STOPS[STOPS.length - 1][1].join(",")})`;
}

const PUMP = { cx: 320, cy: 132, r: 58 };
const SUCTION_Y = PUMP.cy;
const DISCHARGE_Y = 52;
const MOTOR = { x0: 430, x1: 580, y0: 104, y1: 160 };
const BLADES = Array.from({ length: 6 }, (_, i) => i * 60);

function Gauge({ x, y, p, max, stemTo }: { x: number; y: number; p?: number; max: number; stemTo: number }) {
  const frac = p != null && Number.isFinite(p) ? Math.min(Math.max(p / max, 0), 1) : 0;
  const angle = -120 + frac * 240;
  return (
    <g>
      <line x1={x} y1={stemTo} x2={x} y2={y + (stemTo > y ? 16 : -16)} className="pd-stem" />
      <circle cx={x} cy={y} r="16" className="pd-gauge" />
      <path d={`M${x - 11} ${y + 7}A13 13 0 1 1 ${x + 11} ${y + 7}`} className="pd-gauge-arc" />
      <line
        x1={x}
        y1={y}
        x2={x}
        y2={y - 11}
        className="pd-needle"
        style={{ transform: `rotate(${angle}deg)`, transformOrigin: `${x}px ${y}px` }}
      />
      <circle cx={x} cy={y} r="2" className="pd-hub" />
    </g>
  );
}

function bar(p: number | undefined, digits = 3) {
  return p != null && Number.isFinite(p) ? `${p.toFixed(digits)} bar` : "—";
}

function kw(v: number | undefined) {
  return v != null && Number.isFinite(v) ? `${v.toFixed(2)} kW` : "—";
}

export default function PumpDiagram({ flow, P_in, P_out, brake, hydraulic, animate }: Props) {
  const cIn = pressureColor(P_in);
  const cOut = pressureColor(P_out);
  const spin = flow != null && flow > 0 ? Math.max(0.35, Math.min(3, 9000 / flow)) : 2;

  return (
    <figure className={`hx-diagram pd-diagram ${animate ? "is-live" : ""}`}>
      <svg viewBox="0 0 720 240" role="img" aria-label="Centrifugal water pump driven by an electric motor">
        <defs>
          <radialGradient id="pd-casing" cx="0.4" cy="0.35" r="0.75">
            <stop offset="0" stopColor="#2a3a4d" />
            <stop offset="1" stopColor="#141e2a" />
          </radialGradient>
          <linearGradient id="pd-motor" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#2a3a4d" />
            <stop offset="0.5" stopColor="#16212e" />
            <stop offset="1" stopColor="#2a3a4d" />
          </linearGradient>
        </defs>

        <rect x="230" y="200" width="380" height="8" rx="3" className="pd-base" />

        <path d={`M20 ${SUCTION_Y}H${PUMP.cx - 18}`} className="hx-nozzle pd-pipe" stroke={cIn} />
        <path
          d={`M${PUMP.cx + 40} ${PUMP.cy - 40}V${DISCHARGE_Y}H700`}
          className="hx-nozzle pd-pipe"
          stroke={cOut}
        />
        <path d={`M20 ${SUCTION_Y}H${PUMP.cx - 18}`} className="hx-flow hx-flow-water" />
        <path d={`M${PUMP.cx + 40} ${PUMP.cy - 40}V${DISCHARGE_Y}H700`} className="hx-flow hx-flow-air" />

        <path
          d={`M${PUMP.cx} ${PUMP.cy - PUMP.r}A${PUMP.r} ${PUMP.r} 0 1 0 ${PUMP.cx + PUMP.r} ${PUMP.cy}L${PUMP.cx + 54} ${PUMP.cy - 48}L${PUMP.cx + 26} ${PUMP.cy - 62}Z`}
          fill="url(#pd-casing)"
          className="pd-casing"
        />
        <circle cx={PUMP.cx} cy={PUMP.cy} r="42" className="pd-eye" />
        <g className="pd-impeller" style={{ "--spin": `${spin}s`, transformOrigin: `${PUMP.cx}px ${PUMP.cy}px` } as CSSProperties}>
          {BLADES.map((a) => (
            <path
              key={a}
              d={`M${PUMP.cx} ${PUMP.cy - 8}Q${PUMP.cx + 16} ${PUMP.cy - 22} ${PUMP.cx + 10} ${PUMP.cy - 38}`}
              transform={`rotate(${a} ${PUMP.cx} ${PUMP.cy})`}
              stroke={cOut}
            />
          ))}
          <circle cx={PUMP.cx} cy={PUMP.cy} r="8" className="pd-hub" />
        </g>
        <rect x={PUMP.cx - 30} y={PUMP.cy + PUMP.r - 6} width="60" height={200 - (PUMP.cy + PUMP.r - 6)} className="pd-foot" />

        <rect x={PUMP.cx + PUMP.r} y={PUMP.cy - 5} width={MOTOR.x0 - PUMP.cx - PUMP.r} height="10" className="pd-shaft" />
        <rect
          x={MOTOR.x0}
          y={MOTOR.y0}
          width={MOTOR.x1 - MOTOR.x0}
          height={MOTOR.y1 - MOTOR.y0}
          rx="10"
          fill="url(#pd-motor)"
          className="hx-shell"
        />
        {Array.from({ length: 9 }, (_, i) => (
          <line
            key={i}
            x1={MOTOR.x0 + 18 + i * 14}
            x2={MOTOR.x0 + 18 + i * 14}
            y1={MOTOR.y0 + 8}
            y2={MOTOR.y1 - 8}
            className="pd-fin"
          />
        ))}
        <rect x={MOTOR.x0 + 20} y={MOTOR.y1} width={MOTOR.x1 - MOTOR.x0 - 40} height={200 - MOTOR.y1} className="pd-foot" />
        <text x={(MOTOR.x0 + MOTOR.x1) / 2} y={MOTOR.y0 - 10} textAnchor="middle" className="hx-tag">
          Motor
        </text>

        <Gauge x={150} y={98} p={P_in} max={10} stemTo={SUCTION_Y} />
        <Gauge x={640} y={92} p={P_out} max={350} stemTo={DISCHARGE_Y} />

        <text x="20" y="172" textAnchor="start" fill={cIn} className="hx-label">
          Suction {bar(P_in)}
        </text>
        <text x="20" y="188" textAnchor="start" className="pd-sub">
          {flow != null && Number.isFinite(flow) ? `${flow.toLocaleString()} kg/h` : "—"}
        </text>
        <text x="700" y="36" textAnchor="end" fill={cOut} className="hx-label">
          Discharge {bar(P_out)}
        </text>
        <text x={(MOTOR.x0 + MOTOR.x1) / 2} y="226" textAnchor="middle" fill="#ffb347" className="hx-label">
          Brake {kw(brake)}
        </text>
        <text x={PUMP.cx} y="226" textAnchor="middle" fill="#4ade80" className="hx-label">
          Hydraulic {kw(hydraulic)}
        </text>
      </svg>
      <figcaption>
        <span>Centrifugal pump · motor-driven · pressure gauges on suction and discharge</span>
        <span className="hx-scale pd-scale" aria-hidden>
          <i />
          0 → 300 bar
        </span>
      </figcaption>
    </figure>
  );
}
