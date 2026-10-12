export type RiskCode = "L" | "M" | "H" | "VH";

export interface Risk {
  score: number;
  code: RiskCode;
  name: string;
  color: string;
}

export interface WorksheetRow {
  cause: string;
  consequences: string[];
  cc: string;
  safeguards: string[];
  tags: string[];
  c: number;
  l: number;
  risk: Risk;
  recommendations: string[];
}

export interface Deviation {
  deviation: string;
  rows: WorksheetRow[];
}

export interface HazopNode {
  id: number;
  title: string;
  boundary: string;
  design_intent: string;
  design_conditions: string;
  deviations: Deviation[];
}

export interface StudyInfo {
  title?: string;
  project?: string;
  client?: string;
  facility?: string;
  drawing?: string;
  revision?: string;
  date?: string;
  team?: string;
  reference_documents?: string;
  analysis?: string;
}

export interface RiskLevel {
  level: number;
  name: string;
  desc: string;
}

export interface RiskBand {
  code: RiskCode;
  name: string;
  color: string;
}

export interface RiskMatrix {
  name: string;
  source: string | null;
  severity: RiskLevel[];
  likelihood: RiskLevel[];
  bands: RiskBand[];
  /** cells[c - 1][l - 1] */
  cells: RiskCode[][];
}

export interface Worksheet {
  study: StudyInfo;
  nodes: HazopNode[];
  recommendations: Record<string, string>;
  assumptions: string[];
  risk_matrix?: RiskMatrix;
}

export type Box = [number, number, number, number];

export interface Equipment {
  id: string;
  tag: string;
  kind: string;
  description: string;
  api14c: string | null;
  design: Record<string, number>;
  electric: boolean;
  offpage: boolean;
  box: Box;
  boxes?: Box[];
}

export interface Instrument {
  id: string;
  tag: string;
  letters: string;
  description: string;
  category: string;
  variable: string;
  set_point?: string;
  set_psig?: number;
  fire_case?: boolean;
  fail_action?: string;
  voting?: string;
  remark?: string;
  inferred?: boolean;
  box: Box;
}

export interface PipeLine {
  id: string;
  tag: string;
  size: string | null;
  service: string;
  service_name: string | null;
  spec: string;
  spec_known: boolean;
  rating: string | null;
  rating_psig: number | null;
  min_temp_f: number | null;
  max_temp_f: number | null;
  sour: boolean | null;
  material: string | null;
  insulation: string | null;
  box: Box;
  boxes?: Box[];
}

export interface Valve {
  id: string;
  code: string;
  type: string;
  size: string | null;
  attributes: string[];
  box: Box;
}

export interface Connector {
  id: string;
  direction: "source" | "destination";
  description: string;
  line: string | null;
  ref: string | null;
  box: Box;
}

export interface Extraction {
  equipment: Equipment[];
  instruments: Instrument[];
  lines: PipeLine[];
  valves: Valve[];
  connectors: Connector[];
  flags: { sour_service: boolean; car_sealed: boolean; interlocks: number };
  token_count: number;
  tokens: { text: string; box: Box }[];
}

export interface Stats {
  nodes: number;
  deviations: number;
  causes: number;
  recommendations: number;
  risk: Record<RiskCode, number>;
  equipment: number;
  instruments: number;
  lines: number;
  valves: number;
}

export interface JobResult {
  image: { width: number; height: number; url: string; page_count: number };
  text_method: string;
  extraction: Extraction;
  worksheet: Worksheet;
  stats: Stats;
  timings: Record<string, number>;
}

export interface Stage {
  id: string;
  label: string;
}

export type NodeMode = "auto" | "user";

export interface NodePlan {
  title: string;
  tags: string[];
  design_intent: string;
  /** Design intent the engine would write, shown as a hint. */
  auto_intent?: string;
}

export interface NodeReview {
  image: JobResult["image"];
  text_method: string;
  extraction: Extraction;
  proposed_nodes: NodePlan[];
}

export interface Job {
  id: string;
  filename: string;
  status: "queued" | "running" | "review" | "done" | "error";
  stage: string;
  progress: number;
  error: string | null;
  warnings: string[];
  stages: Stage[];
  created: number;
  options: {
    mode: "rules" | "ai";
    provider?: string;
    node_mode?: NodeMode;
    documents?: { piping_spec: string; risk_matrix: string; optional: string[] };
  };
  review?: NodeReview;
  result?: JobResult;
}

export type DocumentKind = "piping-spec" | "risk-matrix";

export interface DocumentCheck {
  kind: DocumentKind;
  name: string;
  summary: string;
  matrix?: RiskMatrix;
}

export interface Provider {
  id: string;
  label: string;
  model: string;
}

export interface Health {
  status: string;
  providers: Provider[];
  max_upload_mb: number;
  formats: string[];
  optional_formats?: string[];
  max_optional_docs?: number;
  samples: string[];
}
