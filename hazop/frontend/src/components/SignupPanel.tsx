"use client";

import clsx from "clsx";
import { ArrowLeft, ArrowRight, LoaderCircle, MailCheck, TriangleAlert, UserPlus } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { notifySignup, saveAccount } from "@/lib/account";
import { registerAccount, requestSignupCode, verifySignupCode } from "@/lib/api";
import type { Verified } from "@/lib/types";
import { Button, Card } from "./ui";

const ROLES = [
  "Process Safety Engineer",
  "Process Engineer",
  "HAZOP Chair / Facilitator",
  "Instrumentation & Control Engineer",
  "Mechanical / Piping Engineer",
  "Operations / Maintenance",
  "HSE Manager",
  "Project / Engineering Manager",
  "Consultant",
  "Student / Academic",
];
const OTHER_ROLE = "Other";

const EMAIL_RE = /^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*@([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$/;
const NAME_RE = /^\p{L}[\p{L} .'-]*$/u;
const DOMAIN_TYPOS: Record<string, string> = {
  "gmial.com": "gmail.com",
  "gmai.com": "gmail.com",
  "gamil.com": "gmail.com",
  "gmail.co": "gmail.com",
  "gmail.con": "gmail.com",
  "gnail.com": "gmail.com",
  "yahoo.co": "yahoo.com",
  "yaho.com": "yahoo.com",
  "yahoo.con": "yahoo.com",
  "hotmial.com": "hotmail.com",
  "hotmail.co": "hotmail.com",
  "outlok.com": "outlook.com",
  "outlook.co": "outlook.com",
};

const input =
  "h-10 w-full rounded-lg border bg-white px-3 text-sm text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-brand-400 focus:ring-2 focus:ring-brand-100";

type Form = { first_name: string; last_name: string; email: string; company: string; role: string; otherRole: string };
type Step = { kind: "form" } | { kind: "code"; email: string; isNew: boolean };

function emailProblem(email: string) {
  const e = email.trim();
  if (!e) return "Enter your email address.";
  if (!EMAIL_RE.test(e)) return "This email address is not valid. Check it for typos.";
  return null;
}

function typoFix(email: string) {
  const [local, domain] = email.trim().toLowerCase().split("@");
  const fix = domain && DOMAIN_TYPOS[domain];
  return fix ? `${local}@${fix}` : null;
}

function Field({ label, error, children, wide }: { label: string; error?: string | null; children: ReactNode; wide?: boolean }) {
  return (
    <label className={clsx("block", wide && "sm:col-span-2")}>
      <span className="mb-1 block text-[11px] font-medium text-slate-600">{label}</span>
      {children}
      {error && <span className="mt-1 block text-[11px] text-rose-600">{error}</span>}
    </label>
  );
}

function signedIn(res: Verified) {
  saveAccount(res.token, res.user);
  if (res.new) void notifySignup(res.user);
}

export default function SignupPanel({ verifyEmail }: { verifyEmail: boolean }) {
  const [mode, setMode] = useState<"signup" | "login">("signup");
  const [step, setStep] = useState<Step>({ kind: "form" });
  const [form, setForm] = useState<Form>({ first_name: "", last_name: "", email: "", company: "", role: "", otherRole: "" });
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [resendIn, setResendIn] = useState(0);

  useEffect(() => {
    if (resendIn <= 0) return;
    const t = setTimeout(() => setResendIn((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [resendIn]);

  const set = (key: keyof Form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const role = form.role === OTHER_ROLE ? form.otherRole.trim() : form.role;
  const nameError = (v: string, label: string) =>
    !v.trim() ? `Enter your ${label}.` : NAME_RE.test(v.trim()) ? null : "Use letters only.";
  const errors =
    mode === "signup"
      ? {
          first_name: nameError(form.first_name, "first name"),
          last_name: nameError(form.last_name, "last name"),
          email: emailProblem(form.email),
          company: form.company.trim() ? null : "Enter your company name.",
          role: role ? null : form.role === OTHER_ROLE ? "Enter your role." : "Choose your role.",
        }
      : { email: emailProblem(form.email) };
  const valid = Object.values(errors).every((e) => !e);
  const show = (key: keyof typeof errors) => (touched ? errors[key] : null);
  const suggestion = typoFix(form.email);

  const sendCode = async (e?: FormEvent) => {
    e?.preventDefault();
    setTouched(true);
    if (!valid) return;
    setBusy(true);
    setError(null);
    try {
      const details =
        mode === "signup"
          ? { first_name: form.first_name, last_name: form.last_name, email: form.email, company: form.company, role }
          : { email: form.email };
      if (!verifyEmail) {
        signedIn(await registerAccount(mode, details));
        return;
      }
      const res = await requestSignupCode(mode, details);
      setStep({ kind: "code", email: res.email, isNew: mode === "signup" });
      setCode("");
      setResendIn(res.resend_after);
      setBusy(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  const verify = async (e?: FormEvent) => {
    e?.preventDefault();
    if (step.kind !== "code" || code.length !== 6) return;
    setBusy(true);
    setError(null);
    try {
      signedIn(await verifySignupCode(step.email, code));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setCode("");
      setBusy(false);
    }
  };

  const switchMode = (m: "signup" | "login") => {
    setMode(m);
    setTouched(false);
    setError(null);
  };

  return (
    <Card className="relative overflow-hidden p-5 sm:p-6">
      <AnimatePresence mode="wait" initial={false}>
        {step.kind === "form" ? (
          <motion.form
            key={`form-${mode}`}
            noValidate
            onSubmit={sendCode}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
          >
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold text-slate-900">
                  {mode === "signup" ? "Sign up free to start" : "Welcome back"}
                </h2>
                <p className="text-xs text-slate-500">
                  {mode === "signup"
                    ? `Create your free account to analyse P&IDs.${verifyEmail ? " We'll email you a code to confirm your address." : ""}`
                    : `Enter the email you signed up with${verifyEmail ? " and we'll send you a code" : ""}.`}
                </p>
              </div>
              <span className="shrink-0 rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-medium text-emerald-700 ring-1 ring-emerald-200">
                Free
              </span>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              {mode === "signup" && (
                <>
                  <Field label="First name" error={show("first_name")}>
                    <input
                      value={form.first_name}
                      onChange={set("first_name")}
                      autoComplete="given-name"
                      maxLength={60}
                      className={clsx(input, show("first_name") ? "border-rose-300" : "border-slate-200")}
                    />
                  </Field>
                  <Field label="Last name" error={show("last_name")}>
                    <input
                      value={form.last_name}
                      onChange={set("last_name")}
                      autoComplete="family-name"
                      maxLength={60}
                      className={clsx(input, show("last_name") ? "border-rose-300" : "border-slate-200")}
                    />
                  </Field>
                </>
              )}
              <Field label={mode === "signup" ? "Work email" : "Email"} error={show("email")} wide>
                <input
                  type="email"
                  value={form.email}
                  onChange={set("email")}
                  onBlur={() => form.email && setTouched(true)}
                  autoComplete="email"
                  inputMode="email"
                  maxLength={254}
                  placeholder="name@company.com"
                  className={clsx(input, show("email") ? "border-rose-300" : "border-slate-200")}
                />
                {suggestion && (
                  <button
                    type="button"
                    onClick={() => setForm((f) => ({ ...f, email: suggestion }))}
                    className="mt-1 text-[11px] text-amber-700 hover:underline"
                  >
                    Did you mean <span className="font-semibold">{suggestion}</span>?
                  </button>
                )}
              </Field>
              {mode === "signup" && (
                <>
                  <Field label="Company name" error={show("company")} wide>
                    <input
                      value={form.company}
                      onChange={set("company")}
                      autoComplete="organization"
                      maxLength={120}
                      className={clsx(input, show("company") ? "border-rose-300" : "border-slate-200")}
                    />
                  </Field>
                  <Field label="Your role" error={form.role === OTHER_ROLE ? null : show("role")} wide>
                    <select
                      value={form.role}
                      onChange={set("role")}
                      className={clsx(input, !form.role && "text-slate-400", show("role") && form.role !== OTHER_ROLE ? "border-rose-300" : "border-slate-200")}
                    >
                      <option value="" disabled>
                        Choose your role
                      </option>
                      {[...ROLES, OTHER_ROLE].map((r) => (
                        <option key={r} value={r} className="text-slate-800">
                          {r}
                        </option>
                      ))}
                    </select>
                  </Field>
                  {form.role === OTHER_ROLE && (
                    <Field label="Describe your role" error={show("role")} wide>
                      <input
                        value={form.otherRole}
                        onChange={set("otherRole")}
                        autoComplete="organization-title"
                        maxLength={80}
                        autoFocus
                        className={clsx(input, show("role") ? "border-rose-300" : "border-slate-200")}
                      />
                    </Field>
                  )}
                </>
              )}
            </div>

            {error && (
              <div className="mt-3 flex items-start gap-2 rounded-lg bg-rose-50 p-2.5 text-xs text-rose-700 ring-1 ring-rose-200">
                <TriangleAlert className="mt-px h-3.5 w-3.5 shrink-0" />
                {error}
              </div>
            )}

            <Button type="submit" size="lg" className="mt-4 w-full" disabled={busy}>
              {busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}
              {busy
                ? verifyEmail
                  ? "Sending code…"
                  : mode === "signup"
                    ? "Signing up…"
                    : "Signing in…"
                : mode === "signup"
                  ? "Sign up free"
                  : verifyEmail
                    ? "Send me a code"
                    : "Sign in"}
            </Button>
            <p className="mt-3 text-center text-xs text-slate-500">
              {mode === "signup" ? "Already signed up? " : "New here? "}
              <button
                type="button"
                onClick={() => switchMode(mode === "signup" ? "login" : "signup")}
                className="font-medium text-brand-600 hover:underline"
              >
                {mode === "signup" ? "Sign in" : "Sign up free"}
              </button>
            </p>
          </motion.form>
        ) : (
          <motion.form
            key="code"
            onSubmit={verify}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
          >
            <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-brand-50 text-brand-600 ring-1 ring-brand-100">
              <MailCheck className="h-6 w-6" />
            </div>
            <h2 className="text-center text-base font-semibold text-slate-900">Check your email</h2>
            <p className="mt-1 text-center text-xs text-slate-500">
              We sent a 6-digit code to <span className="font-semibold text-slate-700">{step.email}</span>. It expires in 10
              minutes. Check your spam folder if you don&apos;t see it.
            </p>
            <input
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
              autoComplete="one-time-code"
              inputMode="numeric"
              autoFocus
              aria-label="6-digit code"
              placeholder="••••••"
              className="mx-auto mt-4 block h-14 w-full max-w-[260px] rounded-xl border border-slate-200 bg-white text-center font-mono text-2xl tracking-[0.5em] text-slate-900 outline-none transition placeholder:text-slate-300 focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
            />
            {error && (
              <div className="mt-3 flex items-start gap-2 rounded-lg bg-rose-50 p-2.5 text-xs text-rose-700 ring-1 ring-rose-200">
                <TriangleAlert className="mt-px h-3.5 w-3.5 shrink-0" />
                {error}
              </div>
            )}
            <Button type="submit" size="lg" className="mt-4 w-full" disabled={busy || code.length !== 6}>
              {busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
              {busy ? "Checking…" : step.isNew ? "Confirm email" : "Sign in"}
            </Button>
            <div className="mt-3 flex items-center justify-between text-xs">
              <button
                type="button"
                onClick={() => {
                  setStep({ kind: "form" });
                  setError(null);
                }}
                className="inline-flex items-center gap-1 text-slate-500 hover:text-slate-800"
              >
                <ArrowLeft className="h-3.5 w-3.5" /> Change email
              </button>
              <button
                type="button"
                disabled={resendIn > 0 || busy}
                onClick={() => sendCode()}
                className="font-medium text-brand-600 hover:underline disabled:cursor-default disabled:text-slate-400 disabled:no-underline"
              >
                {resendIn > 0 ? `Resend code in ${resendIn}s` : "Resend code"}
              </button>
            </div>
          </motion.form>
        )}
      </AnimatePresence>
    </Card>
  );
}
