import { createContext, useContext } from "react";
import type { Risk, RiskBand, RiskCode, RiskLevel, RiskMatrix } from "./types";

export const BAND_ORDER: RiskCode[] = ["L", "M", "H", "VH"];

const DEFAULT_BANDS: (RiskBand & { max: number })[] = [
  { max: 4, code: "L", name: "Low", color: "#C6EFCE" },
  { max: 9, code: "M", name: "Medium", color: "#FFFF80" },
  { max: 16, code: "H", name: "High", color: "#FFC000" },
  { max: 25, code: "VH", name: "Very High", color: "#FF7C80" },
];

const TEXT: Record<RiskCode, string> = { L: "#14532d", M: "#713f12", H: "#7c2d12", VH: "#7f1d1d" };

const SEVERITY: RiskLevel[] = [
  { level: 1, name: "Minor", desc: "First aid injury; negligible release; minimal production impact" },
  { level: 2, name: "Moderate", desc: "Medical treatment / restricted work; minor release; short production loss" },
  { level: 3, name: "Serious", desc: "Lost time injury; contained release; equipment damage / significant production loss" },
  { level: 4, name: "Major", desc: "Permanent disability or single fatality; significant release / fire" },
  { level: 5, name: "Catastrophic", desc: "Multiple fatalities; major fire / explosion; major environmental damage" },
];

const LIKELIHOOD: RiskLevel[] = [
  { level: 1, name: "Remote", desc: "Not expected in facility life (< 1E-4 /yr)" },
  { level: 2, name: "Unlikely", desc: "Could occur in facility life (1E-4 to 1E-3 /yr)" },
  { level: 3, name: "Possible", desc: "Has occurred in industry (1E-3 to 1E-2 /yr)" },
  { level: 4, name: "Likely", desc: "Has occurred at company sites (1E-2 to 1E-1 /yr)" },
  { level: 5, name: "Frequent", desc: "Expected to occur several times (> 1E-1 /yr)" },
];

const scoreCode = (score: number) => (DEFAULT_BANDS.find((b) => score <= b.max) ?? DEFAULT_BANDS[3]).code;

export const DEFAULT_MATRIX: RiskMatrix = {
  name: "5 x 5 risk matrix",
  source: null,
  severity: SEVERITY,
  likelihood: LIKELIHOOD,
  bands: DEFAULT_BANDS.map(({ code, name, color }) => ({ code, name, color })),
  cells: SEVERITY.map((s) => LIKELIHOOD.map((l) => scoreCode(s.level * l.level))),
};

/** The risk matrix of the worksheet being viewed (the project's uploaded matrix). */
export const RiskMatrixContext = createContext<RiskMatrix>(DEFAULT_MATRIX);
export const useRiskMatrix = () => useContext(RiskMatrixContext);

function channels(hex: string) {
  const n = parseInt(hex.replace("#", ""), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function darken(hex: string, f: number) {
  return `rgb(${channels(hex)
    .map((v) => Math.round(v * (1 - f)))
    .join(",")})`;
}

export type BandStyle = RiskBand & { text: string; ring: string };

export function bandFor(code: RiskCode, m: RiskMatrix = DEFAULT_MATRIX): BandStyle {
  const b = m.bands.find((x) => x.code === code) ?? DEFAULT_BANDS.find((x) => x.code === code) ?? DEFAULT_BANDS[0];
  const [r, g, bl] = channels(b.color);
  const dark = 0.299 * r + 0.587 * g + 0.114 * bl < 120;
  return { code: b.code, name: b.name, color: b.color, text: dark ? "#ffffff" : TEXT[b.code], ring: darken(b.color, 0.18) };
}

/** Bands used by the matrix, lowest risk first. */
export function bandsOf(m: RiskMatrix = DEFAULT_MATRIX): BandStyle[] {
  return [...m.bands].sort((a, b) => BAND_ORDER.indexOf(a.code) - BAND_ORDER.indexOf(b.code)).map((b) => bandFor(b.code, m));
}

export function evaluate(c: number, l: number, m: RiskMatrix = DEFAULT_MATRIX): Risk {
  const cc = Math.max(1, Math.min(m.severity.length, c));
  const ll = Math.max(1, Math.min(m.likelihood.length, l));
  const b = bandFor(m.cells[cc - 1][ll - 1], m);
  const fromCell = m.scores?.[cc - 1]?.[ll - 1];
  const score = typeof fromCell === "number" ? fromCell : cc * ll;
  return {
    score,
    code: b.code,
    name: b.name,
    color: b.color,
    higher_is_worse: typeof fromCell === "number" ? m.score_higher_is_worse !== false : true,
  };
}

export const CC_LABEL: Record<string, string> = { S: "Safety", E: "Environment", A: "Asset" };
