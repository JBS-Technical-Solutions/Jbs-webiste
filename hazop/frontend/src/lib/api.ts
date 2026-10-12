import type { DocumentCheck, DocumentKind, Extraction, Health, Job, NodeMode, NodePlan, StudyInfo, Worksheet } from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "/hazop").replace(/\/$/, "");

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new Error(message);
  }
  return res.json() as Promise<T>;
}

export async function getHealth(): Promise<Health> {
  return handle(await fetch(`${API_URL}/api/health`, { cache: "no-store" }));
}

export interface JobOptions {
  mode: "rules" | "ai";
  provider?: string;
  nodeMode: NodeMode;
  study: StudyInfo;
}

export interface ProjectDocuments {
  pipingSpec: File;
  riskMatrix: File;
  optional: File[];
}

export async function createJob(file: File, docs: ProjectDocuments, opts: JobOptions): Promise<Job> {
  const form = new FormData();
  form.set("mode", opts.mode);
  form.set("provider", opts.provider ?? "");
  form.set("node_mode", opts.nodeMode);
  form.set("study", JSON.stringify(opts.study));
  form.set("file", file);
  form.set("piping_spec", docs.pipingSpec);
  form.set("risk_matrix", docs.riskMatrix);
  docs.optional.forEach((f) => form.append("optional_docs", f));
  return handle(await fetch(`${API_URL}/api/jobs`, { method: "POST", body: form }));
}

export async function checkDocument(kind: DocumentKind, file: File): Promise<DocumentCheck> {
  const form = new FormData();
  form.set("file", file);
  return handle(await fetch(`${API_URL}/api/documents/${kind}`, { method: "POST", body: form }));
}

export async function getJob(id: string): Promise<Job> {
  return handle(await fetch(`${API_URL}/api/jobs/${id}`, { cache: "no-store" }));
}

export async function submitNodes(id: string, nodes: NodePlan[]): Promise<Job> {
  return handle(
    await fetch(`${API_URL}/api/jobs/${id}/nodes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nodes: nodes.map(({ title, tags, design_intent }) => ({ title, tags, design_intent })) }),
    }),
  );
}

export function imageUrl(path: string) {
  return `${API_URL}${path}`;
}

export type ExportFormat = "docx" | "xlsx";

export async function downloadExport(fmt: ExportFormat, worksheet: Worksheet, extraction?: Extraction) {
  const res = await fetch(`${API_URL}/api/export/${fmt}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ worksheet, extraction }),
  });
  if (!res.ok) {
    await handle(res);
    return;
  }
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? `HAZOP Worksheet.${fmt}`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
