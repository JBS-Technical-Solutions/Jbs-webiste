"use client";

import clsx from "clsx";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { bandFor } from "@/lib/risk";
import type { RiskCode } from "@/lib/types";

export function Logo({ className, light = false }: { className?: string; light?: boolean }) {
  return (
    <div className={clsx("flex items-center gap-2.5", className)}>
      <div className="relative grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-brand-500 via-brand-600 to-cyan-500 shadow-lg shadow-brand-600/30">
        <svg viewBox="0 0 24 24" className="h-5 w-5 text-white" fill="none" stroke="currentColor" strokeWidth={2}>
          <path d="M12 2.5 3.5 6v6c0 5 3.6 8.6 8.5 9.5 4.9-.9 8.5-4.5 8.5-9.5V6L12 2.5Z" strokeLinejoin="round" />
          <path d="M7.5 12.5h2l1.5-3 2 6 1.5-3h2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
      <div className="leading-none">
        <div className={clsx("text-[15px] font-semibold tracking-tight", light ? "text-white" : "text-slate-900")}>
          HAZOP Studio
        </div>
        <div className={clsx("mt-0.5 text-[11px]", light ? "text-slate-400" : "text-slate-500")}>
          P&amp;ID &rarr; worksheet
        </div>
      </div>
    </div>
  );
}

type Variant = "primary" | "secondary" | "ghost" | "dark";

export function Button({
  variant = "primary",
  size = "md",
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" | "lg" }) {
  return (
    <button
      {...props}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-xl font-medium transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 cursor-pointer active:scale-[0.98]",
        size === "sm" && "h-8 px-3 text-xs",
        size === "md" && "h-10 px-4 text-sm",
        size === "lg" && "h-12 px-6 text-[15px]",
        variant === "primary" &&
          "bg-gradient-to-b from-brand-500 to-brand-600 text-white shadow-md shadow-brand-600/25 hover:from-brand-500 hover:to-brand-700 hover:shadow-lg hover:shadow-brand-600/30",
        variant === "secondary" && "border border-slate-200 bg-white text-slate-700 shadow-sm hover:bg-slate-50 hover:border-slate-300",
        variant === "ghost" && "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
        variant === "dark" && "bg-white/10 text-white ring-1 ring-white/15 hover:bg-white/15",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={clsx("rounded-2xl border border-slate-200/80 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04),0_8px_24px_-12px_rgba(15,23,42,0.08)]", className)}>
      {children}
    </div>
  );
}

export function RiskBadge({ code, score, size = "md" }: { code: RiskCode; score?: number; size?: "sm" | "md" }) {
  const b = bandFor(code);
  return (
    <span
      className={clsx(
        "inline-flex items-center justify-center gap-1 rounded-lg font-semibold tabular-nums ring-1 ring-inset",
        size === "md" ? "min-w-[52px] px-2 py-1 text-xs" : "min-w-[38px] px-1.5 py-0.5 text-[11px]",
      )}
      style={{ background: b.color, color: b.text, boxShadow: `inset 0 0 0 1px ${b.ring}` }}
      title={`${b.name} risk`}
    >
      {score !== undefined && <span>{score}</span>}
      <span className="opacity-80">{code}</span>
    </span>
  );
}

export function Pill({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium", className)}>
      {children}
    </span>
  );
}

export function Tag({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] font-medium text-slate-700 ring-1 ring-inset ring-slate-200",
        className,
      )}
    >
      {children}
    </span>
  );
}

export function SectionTitle({ icon, title, subtitle, right }: { icon?: ReactNode; title: string; subtitle?: string; right?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="flex items-center gap-3">
        {icon && <div className="grid h-9 w-9 place-items-center rounded-xl bg-brand-50 text-brand-600 ring-1 ring-brand-100">{icon}</div>}
        <div>
          <h3 className="text-[15px] font-semibold text-slate-900">{title}</h3>
          {subtitle && <p className="text-xs text-slate-500">{subtitle}</p>}
        </div>
      </div>
      {right}
    </div>
  );
}
