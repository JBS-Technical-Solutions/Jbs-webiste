export const API_BASE = "/api/meoh";

export const BACKEND_OFFLINE = "Backend not reachable";

export type ModelKind = "physics" | "serial" | "parallel" | "pinn";

export const MODEL_ORDER: ModelKind[] = ["physics", "serial", "parallel", "pinn"];

export type TwinInputs = {
  T_in_C: number;
  P_in_bar_g: number;
  F_in_kgmole_h: number;
};

export type Outputs = {
  T_02: number;
  T_04: number;
  T_06: number;
  T_08: number;
  T_10: number;
  P_out_bar_g: number;
  Q_kW: number;
  X_pct: number;
};

export const PROFILE_KEYS = ["T_02", "T_04", "T_06", "T_08", "T_10"] as const;
export const PROFILE_Z = [0.2, 0.4, 0.6, 0.8, 1.0];

export type TwinOutput = {
  model: ModelKind;
  modelLabel: string;
  approach: string;
  source: string;
  outputs: Outputs | null;
  physics_ref: Outputs | null;
  eta: number | null;
  error: string | null;
  warnings: string[];
};

type Range = { min: number; max: number };
type Score = { r2: number; mae: number };

type OutputCol =
  | "T_0.2m_C"
  | "T_0.4m_C"
  | "T_0.6m_C"
  | "T_0.8m_C"
  | "T_1m_C"
  | "P_out_bar_g"
  | "Q_total_kW"
  | "X_overall_pct";

export type BackendInfo = {
  trained_at: string;
  rows: number;
  reactor: {
    reaction: string;
    D_m: number;
    L_m: number;
    h_heat_W_m2K: number;
    T_heat_C: number;
    epsilon: number;
    dp_m: number;
  };
  training_ranges: Record<keyof TwinInputs, Range>;
  output_ranges: Record<OutputCol, Range>;
  models: Record<ModelKind, { selected: string; test: Record<OutputCol, Score> }>;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new Error(`${BACKEND_OFFLINE}. Is the Python server running?`);
  }
  if (res.status === 503) throw new Error(`${BACKEND_OFFLINE}. Is the Python server running?`);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = body?.detail;
    throw new Error(
      typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : `Request failed (${res.status})`,
    );
  }
  return res.json() as Promise<T>;
}

export function fetchInfo() {
  return request<BackendInfo>("/info");
}

export function compareModels(inputs: TwinInputs) {
  return request<TwinOutput[]>("/compare", { method: "POST", body: JSON.stringify(inputs) });
}

export const DEFAULT_INPUTS: TwinInputs = { T_in_C: 350, P_in_bar_g: 2, F_in_kgmole_h: 0.85 };
