"use client";

import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { createJob, createSampleJob, getHealth, getJob, type JobOptions } from "@/lib/api";
import type { Health, Job } from "@/lib/types";
import Home from "./Home";
import ProgressView from "./ProgressView";
import ResultsView from "./ResultsView";
import ErrorView from "./ErrorView";

const LAST_JOB_KEY = "hazop-studio:last-job";
const LAST_JOB_EVENT = "hazop-studio:last-job-changed";

function subscribeLastJob(cb: () => void) {
  window.addEventListener("storage", cb);
  window.addEventListener(LAST_JOB_EVENT, cb);
  return () => {
    window.removeEventListener("storage", cb);
    window.removeEventListener(LAST_JOB_EVENT, cb);
  };
}

function setStoredLastJob(id: string | null) {
  if (id) localStorage.setItem(LAST_JOB_KEY, id);
  else localStorage.removeItem(LAST_JOB_KEY);
  window.dispatchEvent(new Event(LAST_JOB_EVENT));
}

type View =
  | { kind: "home" }
  | { kind: "processing"; job: Job }
  | { kind: "results"; job: Job }
  | { kind: "error"; message: string; job?: Job };

export default function HazopApp() {
  const [view, setView] = useState<View>({ kind: "home" });
  const [health, setHealth] = useState<Health | null>(null);
  const [backendDown, setBackendDown] = useState(false);
  const lastJob = useSyncExternalStore(subscribeLastJob, () => localStorage.getItem(LAST_JOB_KEY), () => null);
  const [submitting, setSubmitting] = useState(false);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const checkHealth = useCallback(() => {
    getHealth()
      .then((h) => {
        setHealth(h);
        setBackendDown(false);
      })
      .catch(() => setBackendDown(true));
  }, []);

  useEffect(checkHealth, [checkHealth]);

  useEffect(() => {
    if (view.kind !== "processing") return;
    let cancelled = false;
    const tick = async () => {
      try {
        const job = await getJob(view.job.id);
        if (cancelled) return;
        if (job.status === "done") {
          setStoredLastJob(job.id);
          setView({ kind: "results", job });
          return;
        }
        if (job.status === "error") {
          setView({ kind: "error", message: job.error ?? "Analysis failed", job });
          return;
        }
        setView((v) => (v.kind === "processing" ? { kind: "processing", job } : v));
      } catch (e) {
        if (cancelled) return;
        setView({ kind: "error", message: e instanceof Error ? e.message : String(e) });
        return;
      }
      pollRef.current = setTimeout(tick, 900);
    };
    pollRef.current = setTimeout(tick, 400);
    return () => {
      cancelled = true;
      if (pollRef.current) clearTimeout(pollRef.current);
    };
    // Poll per job id; job progress updates must not restart the loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view.kind, view.kind === "processing" ? view.job.id : null]);

  const start = async (file: File | null, opts: JobOptions) => {
    setSubmitting(true);
    try {
      const job = file ? await createJob(file, opts) : await createSampleJob(opts);
      setView({ kind: "processing", job });
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      setView({ kind: "error", message: e instanceof Error ? e.message : String(e) });
    } finally {
      setSubmitting(false);
    }
  };

  const openLast = async () => {
    if (!lastJob) return;
    try {
      const job = await getJob(lastJob);
      if (job.status === "done") setView({ kind: "results", job });
      else if (job.status === "error") setView({ kind: "error", message: job.error ?? "Analysis failed", job });
      else setView({ kind: "processing", job });
    } catch {
      setStoredLastJob(null);
    }
  };

  const goHome = () => {
    setView({ kind: "home" });
    checkHealth();
    window.scrollTo({ top: 0 });
  };

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={view.kind}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.25 }}
        className="flex min-h-screen flex-col"
      >
        {view.kind === "home" && (
          <Home
            health={health}
            backendDown={backendDown}
            onRetryHealth={checkHealth}
            onStart={start}
            submitting={submitting}
            lastJob={lastJob}
            onOpenLast={openLast}
          />
        )}
        {view.kind === "processing" && <ProgressView job={view.job} onCancel={goHome} />}
        {view.kind === "results" && <ResultsView job={view.job} onNew={goHome} />}
        {view.kind === "error" && <ErrorView message={view.message} job={view.job} onBack={goHome} />}
      </motion.div>
    </AnimatePresence>
  );
}
