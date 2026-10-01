export const API_BASE = "/api/hx";

export const BACKEND_OFFLINE = "Backend not reachable";

export type ModelKind = "physics" | "serial" | "parallel" | "pinn";

export const MODEL_ORDER: ModelKind[] = ["physics", "serial", "parallel", "pinn"];

export type TwinInputs = {
  m_air_kgh: number;
  m_water_kgh: number;
  T_air_in: number;
  T_water_in: number;
};

export type TwinOutput = {
  model: ModelKind;
  modelLabel: string;
  approach: string;
  source: string;
  U: number;
  T_air_out: number;
  T_water_out: number;
  Q_kW: number;
  NTU: number;
  epsilon: number;
  A_o_total: number;
  iterations: number | null;
  physics_ref: { U: number; T_air_out: number; T_water_out: number } | null;
  hydraulics: {
    h_i: number;
    h_o: number;
    Re_tube: number;
    Re_shell: number;
    dP_tube_kPa: number;
    dP_shell_kPa: number;
  };
  extra: Record<string, number>;
  warnings: string[];
};

type Score = { r2: number; mae: number; rmse: number };

export type BackendInfo = {
  trained_at: string;
  rows: number;
  geometry: { N_tubes: number; L_m: number; A_o_m2: number; type: string };
  training_ranges: Record<keyof TwinInputs, { min: number; max: number }>;
  output_ranges: Partial<Record<"U" | "T_air_out" | "T_water_out" | "Q_kW", { min: number; max: number }>>;
  models: Record<
    ModelKind,
    { selected: string; test: { U: Score; T_air_out: Score; T_water_out: Score } }
  >;
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

export const DEFAULT_INPUTS: TwinInputs = { m_air_kgh: 50000, m_water_kgh: 25000, T_air_in: 350, T_water_in: 30 };
