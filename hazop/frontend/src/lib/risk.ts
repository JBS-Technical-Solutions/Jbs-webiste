import type { Risk, RiskCode } from "./types";

export const RISK_BANDS: { max: number; code: RiskCode; name: string; color: string; text: string; ring: string }[] = [
  { max: 4, code: "L", name: "Low", color: "#C6EFCE", text: "#14532d", ring: "#86d39a" },
  { max: 9, code: "M", name: "Medium", color: "#FFFF80", text: "#713f12", ring: "#e3d64a" },
  { max: 16, code: "H", name: "High", color: "#FFC000", text: "#7c2d12", ring: "#e0a200" },
  { max: 25, code: "VH", name: "Very High", color: "#FF7C80", text: "#7f1d1d", ring: "#f0565b" },
];

export const SEVERITY = [
  { level: 1, name: "Minor", desc: "First aid injury; negligible release; minimal production impact" },
  { level: 2, name: "Moderate", desc: "Medical treatment / restricted work; minor release; short production loss" },
  { level: 3, name: "Serious", desc: "Lost time injury; contained release; equipment damage / significant production loss" },
  { level: 4, name: "Major", desc: "Permanent disability or single fatality; significant release / fire" },
  { level: 5, name: "Catastrophic", desc: "Multiple fatalities; major fire / explosion; major environmental damage" },
];

export const LIKELIHOOD = [
  { level: 1, name: "Remote", desc: "Not expected in facility life (< 1E-4 /yr)" },
  { level: 2, name: "Unlikely", desc: "Could occur in facility life (1E-4 to 1E-3 /yr)" },
  { level: 3, name: "Possible", desc: "Has occurred in industry (1E-3 to 1E-2 /yr)" },
  { level: 4, name: "Likely", desc: "Has occurred at company sites (1E-2 to 1E-1 /yr)" },
  { level: 5, name: "Frequent", desc: "Expected to occur several times (> 1E-1 /yr)" },
];

export function bandFor(code: RiskCode) {
  return RISK_BANDS.find((b) => b.code === code) ?? RISK_BANDS[0];
}

export function evaluate(c: number, l: number): Risk {
  const score = c * l;
  const b = RISK_BANDS.find((x) => score <= x.max) ?? RISK_BANDS[RISK_BANDS.length - 1];
  return { score, code: b.code, name: b.name, color: b.color };
}

export const CC_LABEL: Record<string, string> = { S: "Safety", E: "Environment", A: "Asset" };
