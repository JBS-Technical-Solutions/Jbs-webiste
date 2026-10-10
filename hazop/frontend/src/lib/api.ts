import type { Extraction, Health, Job, StudyInfo, Worksheet } from "./types";

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
  study: StudyInfo;
}

function optionsForm(opts: JobOptions, form = new FormData()) {
  form.set("mode", opts.mode);
  form.set("provider", opts.provider ?? "");
  form.set("study", JSON.stringify(opts.study));
  return form;
}

export async function createJob(file: File, opts: JobOptions): Promise<Job> {
  const form = optionsForm(opts);
  form.set("file", file);
  return handle(await fetch(`${API_URL}/api/jobs`, { method: "POST", body: form }));
}

export async function createSampleJob(opts: JobOptions): Promise<Job> {
  return handle(await fetch(`${API_URL}/api/jobs/sample`, { method: "POST", body: optionsForm(opts) }));
}

export async function getJob(id: string): Promise<Job> {
  return handle(await fetch(`${API_URL}/api/jobs/${id}`, { cache: "no-store" }));
}

export function imageUrl(path: string) {
  return `${API_URL}${path}`;
}

export type ExportFormat = "docx" | "xlsx" | "json";

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
