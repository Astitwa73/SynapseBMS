/**
 * Shared presentation primitives.
 *
 * Every card, label, badge and readout comes from here, so spacing, borders and
 * type scale cannot drift between panels. Anything that appears twice in the UI
 * appears once in this file.
 */

import type { ReactNode } from "react";
import { SEVERITY_CLASSES, type Severity } from "../../lib/format";

interface CardProps {
  title?: string;
  subtitle?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  /** Draws attention to the panel currently doing work in the decision cycle. */
  active?: boolean;
}

export function Card({
  title,
  subtitle,
  action,
  children,
  className = "",
  active = false,
}: CardProps) {
  return (
    <section
      className={`flex flex-col rounded-lg border bg-surface transition-colors duration-500 ${
        active ? "border-brand/60 shadow-[0_0_0_3px_var(--color-brand-tint)]" : "border-line"
      } ${className}`}
    >
      {(title || action) && (
        <header className="flex items-baseline justify-between gap-3 border-b border-line px-4 py-2.5">
          <div className="min-w-0">
            {title && (
              <h2 className="text-[11px] font-semibold uppercase tracking-[0.09em] text-muted">
                {title}
              </h2>
            )}
            {subtitle && <div className="mt-0.5 text-xs text-faint">{subtitle}</div>}
          </div>
          {action}
        </header>
      )}
      <div className="min-h-0 flex-1 p-4">{children}</div>
    </section>
  );
}

export function Badge({
  children,
  severity = "neutral",
  className = "",
}: {
  children: ReactNode;
  severity?: Severity;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded border px-1.5 py-0.5 text-[11px] font-medium ${SEVERITY_CLASSES[severity]} ${className}`}
    >
      {children}
    </span>
  );
}

export function StatusDot({
  severity = "neutral",
  pulse = false,
}: {
  severity?: Severity;
  pulse?: boolean;
}) {
  const fill: Record<Severity, string> = {
    ok: "bg-ok",
    warn: "bg-warn",
    crit: "bg-crit",
    info: "bg-info",
    neutral: "bg-line-strong",
  };
  return (
    <span className="relative flex h-2 w-2 shrink-0">
      {pulse && (
        <span
          className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${fill[severity]}`}
        />
      )}
      <span className={`relative inline-flex h-2 w-2 rounded-full ${fill[severity]}`} />
    </span>
  );
}

/** A labelled figure. `mono` is the default because these values update live and
 * tabular digits stop the layout shifting as they change. */
export function Readout({
  label,
  value,
  unit,
  hint,
  severity,
  size = "md",
}: {
  label: string;
  value: string;
  unit?: string;
  hint?: ReactNode;
  severity?: Severity;
  size?: "sm" | "md" | "lg";
}) {
  const sizes = {
    sm: "text-base",
    md: "text-xl",
    lg: "text-3xl",
  };
  const tone =
    severity && severity !== "neutral"
      ? { ok: "text-ok", warn: "text-warn", crit: "text-crit", info: "text-info" }[severity]
      : "text-ink";

  return (
    <div className="min-w-0">
      <div className="text-[11px] font-medium uppercase tracking-[0.07em] text-faint">
        {label}
      </div>
      <div className={`tabular mt-0.5 font-semibold leading-tight ${sizes[size]} ${tone}`}>
        {value}
        {unit && <span className="ml-1 text-xs font-normal text-muted">{unit}</span>}
      </div>
      {hint && <div className="mt-0.5 truncate text-[11px] text-faint">{hint}</div>}
    </div>
  );
}

/** Small key/value line used inside dense panels. */
export function Field({
  label,
  children,
  className = "",
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`flex items-baseline justify-between gap-3 ${className}`}>
      <span className="shrink-0 text-[11px] uppercase tracking-[0.06em] text-faint">
        {label}
      </span>
      <span className="tabular min-w-0 truncate text-right text-sm font-medium text-ink">
        {children}
      </span>
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-sunken ${className}`} />;
}

/** Shown wherever real data has not arrived, so no panel ever renders zeros it
 * does not have. */
export function AwaitingData({ label = "Awaiting simulation data" }: { label?: string }) {
  return (
    <div className="flex h-full min-h-24 flex-col items-center justify-center gap-2 text-center">
      <div className="h-1 w-16 overflow-hidden rounded-full bg-sunken">
        <div className="h-full w-1/3 animate-[pulse_1.4s_ease-in-out_infinite] rounded-full bg-line-strong" />
      </div>
      <p className="text-xs text-faint">{label}</p>
    </div>
  );
}
