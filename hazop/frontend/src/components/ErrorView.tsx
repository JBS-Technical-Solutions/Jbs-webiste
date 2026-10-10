"use client";

import { ArrowLeft, TriangleAlert } from "lucide-react";
import type { Job } from "@/lib/types";
import { Button, Card, Logo } from "./ui";

export default function ErrorView({ message, job, onBack }: { message: string; job?: Job; onBack: () => void }) {
  return (
    <div className="flex min-h-screen flex-col bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-7xl px-5 py-4 sm:px-8">
          <Logo />
        </div>
      </header>
      <main className="grid flex-1 place-items-center px-5 py-16">
        <Card className="w-full max-w-lg p-8 text-center">
          <div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-rose-50 text-rose-600 ring-1 ring-rose-200">
            <TriangleAlert className="h-6 w-6" />
          </div>
          <h1 className="mt-5 text-xl font-semibold text-slate-900">We couldn&apos;t finish this analysis</h1>
          {job && <p className="mt-1 text-sm text-slate-500">{job.filename}</p>}
          <p className="mx-auto mt-4 max-w-md rounded-xl bg-slate-50 px-4 py-3 text-left font-mono text-xs leading-relaxed text-slate-700 ring-1 ring-slate-200">
            {message}
          </p>
          <ul className="mx-auto mt-5 max-w-md space-y-1 text-left text-sm text-slate-500">
            <li>&bull; Make sure the backend is running on port 8000.</li>
            <li>&bull; Upload a single P&amp;ID sheet as PDF or a sharp image (300 dpi or better).</li>
          </ul>
          <Button className="mt-7" onClick={onBack}>
            <ArrowLeft className="h-4 w-4" /> Back to upload
          </Button>
        </Card>
      </main>
    </div>
  );
}
