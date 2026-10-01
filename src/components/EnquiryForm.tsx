"use client";

import { useState, type FormEvent } from "react";
import { AnimatePresence, motion } from "motion/react";
import { easeOut } from "./motion/easing";
import { site } from "@/lib/site";

const interests = ["Digital Twins", "Advanced Analytics", "Workflow Digitalization", "Strategic Development", "Other"];

type Status = "idle" | "sending" | "sent" | "error";

const field =
  "peer w-full border-0 border-b border-ink/20 bg-transparent px-0 pb-3 pt-6 text-lg outline-none transition-colors placeholder:text-transparent focus:border-accent";
const floatingLabel =
  "pointer-events-none absolute left-0 top-6 text-lg text-muted transition-all duration-300 peer-focus:top-0 peer-focus:text-xs peer-focus:uppercase peer-focus:tracking-[0.2em] peer-focus:text-accent-deep peer-[:not(:placeholder-shown)]:top-0 peer-[:not(:placeholder-shown)]:text-xs peer-[:not(:placeholder-shown)]:uppercase peer-[:not(:placeholder-shown)]:tracking-[0.2em]";

function Field({ name, label, type = "text", required = false }: { name: string; label: string; type?: string; required?: boolean }) {
  return (
    <label className="relative block">
      <input name={name} type={type} required={required} placeholder={label} className={field} />
      <span className={floatingLabel}>
        {label}
        {required && " *"}
      </span>
    </label>
  );
}

export default function EnquiryForm() {
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState("");

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const accessKey = process.env.NEXT_PUBLIC_WEB3FORMS_ACCESS_KEY;

    if (!accessKey) {
      setError(`The enquiry form isn't connected yet. Please email us at ${site.email}.`);
      setStatus("error");
      return;
    }

    setStatus("sending");
    const data = new FormData(form);
    data.append("access_key", accessKey);
    data.append("subject", `New enquiry from ${data.get("name")} — ${site.name} website`);
    data.append("from_name", `${site.name} website`);

    try {
      const response = await fetch("https://api.web3forms.com/submit", { method: "POST", body: data });
      const result = await response.json();
      if (!result.success) throw new Error(result.message);
      form.reset();
      setStatus("sent");
    } catch {
      setError(`Something went wrong while sending. Please try again or email us at ${site.email}.`);
      setStatus("error");
    }
  }

  return (
    <AnimatePresence mode="wait">
      {status === "sent" ? (
        <motion.div
          key="sent"
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, ease: easeOut }}
          className="flex min-h-[420px] flex-col justify-center"
          role="status"
        >
          <span className="flex h-16 w-16 items-center justify-center rounded-full bg-accent text-white">
            <svg viewBox="0 0 24 24" className="h-7 w-7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <motion.path
                d="M5 12.5l4.5 4.5L19 7.5"
                initial={{ pathLength: 0 }}
                animate={{ pathLength: 1 }}
                transition={{ delay: 0.3, duration: 0.6, ease: easeOut }}
              />
            </svg>
          </span>
          <h2 className="mt-8 text-4xl font-semibold uppercase leading-[0.95] tracking-[-0.03em] sm:text-5xl">
            Thank you.
          </h2>
          <p className="mt-4 max-w-md text-lg leading-relaxed text-muted">
            Your enquiry has been sent. We&apos;ll get back to you shortly.
          </p>
          <button
            type="button"
            onClick={() => setStatus("idle")}
            className="mt-10 self-start text-xs font-semibold uppercase tracking-[0.2em] text-accent-deep underline underline-offset-8 hover:text-ink"
          >
            Send another enquiry
          </button>
        </motion.div>
      ) : (
        <motion.form
          key="form"
          onSubmit={handleSubmit}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0, y: -16 }}
          transition={{ duration: 0.5 }}
          className="space-y-8"
        >
          <input type="checkbox" name="botcheck" className="hidden" tabIndex={-1} autoComplete="off" />

          <div className="grid gap-8 sm:grid-cols-2">
            <Field name="name" label="Full name" required />
            <Field name="email" label="Work email" type="email" required />
            <Field name="company" label="Company" />
            <Field name="phone" label="Phone" type="tel" />
          </div>

          <fieldset>
            <legend className="text-xs font-semibold uppercase tracking-[0.2em] text-muted">I&apos;m interested in</legend>
            <div className="mt-4 flex flex-wrap gap-2">
              {interests.map((interest, i) => (
                <label key={interest} className="cursor-pointer">
                  <input
                    type="radio"
                    name="interest"
                    value={interest}
                    defaultChecked={i === 0}
                    className="peer sr-only"
                  />
                  <span className="block rounded-full border border-ink/15 px-4 py-2 text-sm transition-colors hover:border-accent peer-checked:border-accent peer-checked:bg-accent peer-checked:text-white peer-focus-visible:ring-2 peer-focus-visible:ring-accent/40">
                    {interest}
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          <label className="relative block">
            <textarea name="message" required rows={4} placeholder="Tell us about your process" className={`${field} resize-none`} />
            <span className={floatingLabel}>Tell us about your process *</span>
          </label>

          <div className="flex flex-col gap-4 pt-2 sm:flex-row sm:items-center sm:justify-between">
            <button
              type="submit"
              disabled={status === "sending"}
              className="group inline-flex items-center justify-center gap-3 rounded-full bg-accent px-8 py-4 text-xs font-semibold uppercase tracking-[0.2em] text-white transition-colors hover:bg-accent-deep disabled:opacity-60"
            >
              {status === "sending" ? "Sending…" : "Send enquiry"}
              <svg viewBox="0 0 24 24" className="h-4 w-4 transition-transform group-hover:translate-x-1" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
            </button>
            <p className="text-sm text-muted" aria-live="polite">
              {status === "error" ? <span className="text-accent-deep">{error}</span> : "Your details go straight to our engineering team."}
            </p>
          </div>
        </motion.form>
      )}
    </AnimatePresence>
  );
}
