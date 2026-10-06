export const API_BASE = "/api/pump";

export const BACKEND_OFFLINE = "Backend not reachable";

export type ModelKind = "serial" | "parallel" | "pinn";

export const MODEL_ORDER: ModelKind[] = ["serial", "parallel", "pinn"];

export type TwinInputs = {
  flow_kgh: number;
  P_in_bar: number;
  P_out_bar: number;
  rho: number;
};

export type Outputs = {
  brake_kW: number;
  hydraulic_kW: number;
  efficiency: number;
  physics_brake_kW: number | null;
  residual_kW: number | null;
};

export type TwinOutput = {
  model: ModelKind;
  modelLabel: string;
  approach: string;
  source: string;
  outputs: Outputs | null;
  error: string | null;
  warnings: string[];
};

export type ModelCurve = {
  model: ModelKind;
  points: { flow_kgh: number; brake_kW: number | null }[];
};

type Range = { min: number; max: number };
type Score = { r2: number; mae: number };

export type BackendInfo = {
  trained_at: string;
  rows: number;
  test_rows: number;
  training_ranges: Record<keyof TwinInputs, Range>;
  output_ranges: Record<"brake_kW" | "hydraulic_kW" | "efficiency", Range>;
  models: Record<ModelKind, { selected: string; test: Score }>;
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

export function fetchCurve(inputs: TwinInputs) {
  return request<ModelCurve[]>("/curve", { method: "POST", body: JSON.stringify(inputs) });
}

export const DEFAULT_INPUTS: TwinInputs = { flow_kgh: 13000, P_in_bar: 6.013, P_out_bar: 175, rho: 999.9 };
