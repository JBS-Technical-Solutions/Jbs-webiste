"use client";

type Props = {
  T_air_in?: number;
  T_air_out?: number;
  T_water_in?: number;
  T_water_out?: number;
  animate: boolean;
};

const STOPS: [number, [number, number, number]][] = [
  [20, [62, 207, 207]],
  [60, [95, 211, 160]],
  [120, [240, 199, 94]],
  [250, [255, 138, 61]],
  [450, [255, 77, 61]],
  [700, [214, 32, 74]],
];

export function tempColor(t: number | undefined) {
  if (t == null || !Number.isFinite(t)) return "rgb(120, 140, 160)";
  if (t <= STOPS[0][0]) return `rgb(${STOPS[0][1].join(",")})`;
  for (let i = 1; i < STOPS.length; i++) {
    const [t1, c1] = STOPS[i];
    if (t <= t1) {
      const [t0, c0] = STOPS[i - 1];
      const k = (t - t0) / (t1 - t0);
      return `rgb(${c0.map((c, j) => Math.round(c + (c1[j] - c) * k)).join(",")})`;
    }
  }
  return `rgb(${STOPS[STOPS.length - 1][1].join(",")})`;
}

function label(name: string, t: number | undefined) {
  return `${name} ${t != null && Number.isFinite(t) ? t.toFixed(1) : "—"}°C`;
}

const SHELL = { x0: 130, x1: 590, y0: 62, y1: 198 };
const PASS1_Y = [145, 160, 175];
const PASS2_Y = [115, 100, 85];
const BAFFLES: { x: number; fromTop: boolean }[] = [
  { x: 205, fromTop: true },
  { x: 285, fromTop: false },
  { x: 365, fromTop: true },
  { x: 445, fromTop: false },
  { x: 525, fromTop: true },
];

const pass1 = PASS1_Y.map((y) => `M${SHELL.x0} ${y}H${SHELL.x1}`).join("");
const pass2 = PASS2_Y.map((y) => `M${SHELL.x1} ${y}H${SHELL.x0}`).join("");
const turns = PASS1_Y.map((y, i) => `M${SHELL.x1} ${y}C${SHELL.x1 + 42} ${y} ${SHELL.x1 + 42} ${PASS2_Y[i]} ${SHELL.x1} ${PASS2_Y[i]}`).join("");
const airPath = "M555 24V184H485V76H405V184H325V76H245V184H165V236";

export default function ExchangerDiagram({ T_air_in, T_air_out, T_water_in, T_water_out, animate }: Props) {
  const T_water_mid = T_water_in != null && T_water_out != null ? (T_water_in + T_water_out) / 2 : undefined;
  const cWin = tempColor(T_water_in);
  const cWmid = tempColor(T_water_mid);
  const cWout = tempColor(T_water_out);
  const cAin = tempColor(T_air_in);
  const cAout = tempColor(T_air_out);

  return (
    <figure className={`hx-diagram ${animate ? "is-live" : ""}`}>
      <svg viewBox="0 0 720 260" role="img" aria-label="Shell and tube heat exchanger, 1 shell pass, 2 tube passes">
        <defs>
          <linearGradient id="hx-pass1" gradientUnits="userSpaceOnUse" x1={SHELL.x0} x2={SHELL.x1} y1="0" y2="0">
            <stop offset="0" stopColor={cWin} />
            <stop offset="1" stopColor={cWmid} />
          </linearGradient>
          <linearGradient id="hx-pass2" gradientUnits="userSpaceOnUse" x1={SHELL.x1} x2={SHELL.x0} y1="0" y2="0">
            <stop offset="0" stopColor={cWmid} />
            <stop offset="1" stopColor={cWout} />
          </linearGradient>
          <linearGradient id="hx-air" gradientUnits="userSpaceOnUse" x1="555" x2="165" y1="0" y2="0">
            <stop offset="0" stopColor={cAin} />
            <stop offset="1" stopColor={cAout} />
          </linearGradient>
          <linearGradient id="hx-shell" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#2a3a4d" />
            <stop offset="0.5" stopColor="#16212e" />
            <stop offset="1" stopColor="#2a3a4d" />
          </linearGradient>
        </defs>

        <rect x="70" y="70" width="60" height="120" rx="10" className="hx-body" />
        <line x1="70" y1="130" x2="130" y2="130" className="hx-partition" />
        <rect x={SHELL.x1 - 10} y="70" width="60" height="120" rx="26" className="hx-body" />
        <rect
          x={SHELL.x0}
          y={SHELL.y0}
          width={SHELL.x1 - SHELL.x0}
          height={SHELL.y1 - SHELL.y0}
          rx="8"
          fill="url(#hx-shell)"
          className="hx-shell"
        />

        {BAFFLES.map((b) => (
          <rect
            key={b.x}
            x={b.x - 2}
            y={b.fromTop ? SHELL.y0 : SHELL.y0 + 28}
            width="4"
            height={SHELL.y1 - SHELL.y0 - 28}
            className="hx-baffle"
          />
        ))}

        <path d={airPath} className="hx-air" stroke="url(#hx-air)" />
        <path d={airPath} className="hx-flow hx-flow-air" />

        <path d={pass1} className="hx-tube" stroke="url(#hx-pass1)" />
        <path d={pass2} className="hx-tube" stroke="url(#hx-pass2)" />
        <path d={turns} className="hx-tube" stroke={cWmid} />
        <path d="M100 226V190" className="hx-nozzle" stroke={cWin} />
        <path d="M100 70V34" className="hx-nozzle" stroke={cWout} />
        <path d={`M100 226V190 ${pass1}${turns}${pass2}M100 70V34`} className="hx-flow hx-flow-water" />

        <line x1={SHELL.x0} y1={SHELL.y0 - 4} x2={SHELL.x0} y2={SHELL.y1 + 4} className="hx-tubesheet" />
        <line x1={SHELL.x1} y1={SHELL.y0 - 4} x2={SHELL.x1} y2={SHELL.y1 + 4} className="hx-tubesheet" />

        <text x="555" y="16" textAnchor="middle" fill={cAin} className="hx-label">
          {label("Air in", T_air_in)}
        </text>
        <text x="175" y="250" textAnchor="start" fill={cAout} className="hx-label">
          {label("Air out", T_air_out)}
        </text>
        <text x="100" y="244" textAnchor="middle" fill={cWin} className="hx-label">
          {label("Water in", T_water_in)}
        </text>
        <text x="100" y="26" textAnchor="middle" fill={cWout} className="hx-label">
          {label("Water out", T_water_out)}
        </text>
        <text x="100" y="106" textAnchor="middle" className="hx-tag">
          pass 2
        </text>
        <text x="100" y="162" textAnchor="middle" className="hx-tag">
          pass 1
        </text>
      </svg>
      <figcaption>
        <span>TEMA A · 1 shell pass · 2 tube passes · segmental baffles</span>
        <span className="hx-scale" aria-hidden>
          <i />
          20°C → 700°C
        </span>
      </figcaption>
    </figure>
  );
}
