"use client";

const COLOR_STOPS: [number, [number, number, number]][] = [
  [20, [62, 207, 207]],
  [60, [95, 211, 160]],
  [110, [240, 199, 94]],
  [180, [255, 138, 61]],
  [240, [255, 77, 61]],
  [300, [214, 32, 74]],
];

function tempColor(t: number | undefined) {
  if (t == null || !Number.isFinite(t)) return "rgb(120, 140, 160)";
  if (t <= COLOR_STOPS[0][0]) return `rgb(${COLOR_STOPS[0][1].join(",")})`;
  for (let i = 1; i < COLOR_STOPS.length; i++) {
    const [t1, c1] = COLOR_STOPS[i];
    if (t <= t1) {
      const [t0, c0] = COLOR_STOPS[i - 1];
      const k = (t - t0) / (t1 - t0);
      return `rgb(${c0.map((c, j) => Math.round(c + (c1[j] - c) * k)).join(",")})`;
    }
  }
  return `rgb(${COLOR_STOPS[COLOR_STOPS.length - 1][1].join(",")})`;
}

type Props = {
  T_in?: number;
  profile?: (number | undefined)[];
  T_heat: number;
  animate: boolean;
};

const TUBE = { x0: 120, x1: 600, y0: 100, y1: 140 };
const JACKET = { x0: 120, x1: 600, y0: 72, y1: 168 };
const MID = (TUBE.y0 + TUBE.y1) / 2;
const SENSOR_Z = [0.2, 0.4, 0.6, 0.8, 1.0];

const zx = (z: number) => TUBE.x0 + z * (TUBE.x1 - TUBE.x0);

const PELLETS = Array.from({ length: 3 }, (_, row) =>
  Array.from({ length: 47 }, (_, i) => ({
    cx: TUBE.x0 + 7 + i * 10 + (row % 2) * 5,
    cy: TUBE.y0 + 8 + row * 12,
  })).filter((p) => p.cx < TUBE.x1 - 4),
).flat();

function coil(y: number) {
  const step = 16;
  let d = `M${JACKET.x0 + 8} ${y}`;
  for (let x = JACKET.x0 + 8; x < JACKET.x1 - 8; x += step) d += `q${step / 4} -6 ${step / 2} 0t${step / 2} 0`;
  return d;
}

function temp(t: number | undefined) {
  return t != null && Number.isFinite(t) ? `${t.toFixed(1)}°C` : "—";
}

export default function ReactorDiagram({ T_in, profile = [], T_heat, animate }: Props) {
  const T_out = profile[profile.length - 1];
  const stops = [T_in, ...SENSOR_Z.map((_, i) => profile[i])];
  const cHeat = tempColor(T_heat);

  return (
    <figure className={`hx-diagram rx-diagram ${animate ? "is-live" : ""}`}>
      <svg viewBox="0 0 720 230" role="img" aria-label="Heated packed-bed tubular reactor for methanol decomposition">
        <defs>
          <linearGradient id="rx-bed" gradientUnits="userSpaceOnUse" x1={TUBE.x0} x2={TUBE.x1} y1="0" y2="0">
            {stops.map((t, i) => (
              <stop key={i} offset={i === 0 ? 0 : SENSOR_Z[i - 1]} stopColor={tempColor(t)} />
            ))}
          </linearGradient>
          <linearGradient id="rx-jacket" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#2a3a4d" />
            <stop offset="0.5" stopColor="#16212e" />
            <stop offset="1" stopColor="#2a3a4d" />
          </linearGradient>
        </defs>

        <rect
          x={JACKET.x0}
          y={JACKET.y0}
          width={JACKET.x1 - JACKET.x0}
          height={JACKET.y1 - JACKET.y0}
          rx="10"
          fill="url(#rx-jacket)"
          className="hx-shell"
        />
        <path d={coil((JACKET.y0 + TUBE.y0) / 2)} className="rx-coil" stroke={cHeat} />
        <path d={coil((JACKET.y1 + TUBE.y1) / 2)} className="rx-coil" stroke={cHeat} />

        <path d={`M28 ${MID}H${TUBE.x0}`} className="hx-nozzle" stroke={tempColor(T_in)} />
        <path d={`M${TUBE.x1} ${MID}H692`} className="hx-nozzle" stroke={tempColor(T_out)} />

        <rect
          x={TUBE.x0}
          y={TUBE.y0}
          width={TUBE.x1 - TUBE.x0}
          height={TUBE.y1 - TUBE.y0}
          rx="4"
          fill="url(#rx-bed)"
          className="rx-bed"
        />
        {PELLETS.map((p) => (
          <circle key={`${p.cx}-${p.cy}`} cx={p.cx} cy={p.cy} r="3.4" className="rx-pellet" />
        ))}
        <path d={`M28 ${MID}H692`} className="hx-flow hx-flow-air" />

        <line x1={TUBE.x0} y1={JACKET.y0 - 4} x2={TUBE.x0} y2={JACKET.y1 + 4} className="hx-tubesheet" />
        <line x1={TUBE.x1} y1={JACKET.y0 - 4} x2={TUBE.x1} y2={JACKET.y1 + 4} className="hx-tubesheet" />

        {SENSOR_Z.map((z, i) => (
          <g key={z}>
            <line x1={zx(z)} y1={TUBE.y1} x2={zx(z)} y2={JACKET.y1 + 10} className="rx-probe" />
            <circle cx={zx(z)} cy={JACKET.y1 + 10} r="3" fill={tempColor(profile[i])} />
            <text x={zx(z) - (z === 1 ? 4 : 0)} y={JACKET.y1 + 28} textAnchor={z === 1 ? "end" : "middle"} className="rx-sub">
              {z.toFixed(1)} m
            </text>
            <text
              x={zx(z) - (z === 1 ? 4 : 0)}
              y={JACKET.y1 + 44}
              textAnchor={z === 1 ? "end" : "middle"}
              fill={tempColor(profile[i])}
              className="hx-label"
            >
              {temp(profile[i])}
            </text>
          </g>
        ))}

      </svg>
      <figcaption>
        <span>Packed-bed tubular reactor · temperature probes along the bed</span>
        <span className="hx-scale" aria-hidden>
          <i />
          20°C → 300°C
        </span>
      </figcaption>
    </figure>
  );
}
