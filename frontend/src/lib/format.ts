/**
 * Formatting.
 *
 * Centralised because units and precision must be consistent everywhere: a value
 * shown as 26.0 in one card and 26 in another reads as two different readings.
 *
 * The null rule matters most. The backend reports null for a sensor it genuinely
 * cannot supply, and rendering that as 0 would turn a wiring problem into a
 * plausible-looking measurement. Everything here renders unavailable data as an
 * em dash, never as a number.
 */

import type { AirQualityBand, ComfortBand } from "../api/types";

export const NO_VALUE = "—";

export function number(
  value: number | null | undefined,
  digits = 1,
  unit?: string,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NO_VALUE;
  const text = value.toFixed(digits);
  return unit ? `${text} ${unit}` : text;
}

export function signed(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NO_VALUE;
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;
}

export function percent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NO_VALUE;
  return `${value.toFixed(digits)}%`;
}

export function integer(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NO_VALUE;
  return Math.round(value).toLocaleString();
}

export function seconds(ms: number): string {
  return `${(ms / 1000).toFixed(1)}s`;
}

/** "07-02 14:00" -> "Wed 2 Jul, 14:00". The simulated year is arbitrary, so the
 * weekday comes from the model's own calendar rather than being asserted. */
export function clockLabel(label: string): string {
  const match = /^(\d{2})-(\d{2}) (\d{2}):(\d{2})$/.exec(label);
  if (!match) return label;

  const [, month, day, hour, minute] = match;
  const months = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ];
  return `${Number(day)} ${months[Number(month) - 1]} · ${hour}:${minute}`;
}

export const ACTION_LABELS: Record<string, string> = {
  raise_setpoint: "Raise setpoint",
  lower_setpoint: "Lower setpoint",
  reduce_lighting: "Reduce lighting",
  hold: "Hold",
};

/** Arrows encode direction of change, so an action is readable at a glance and
 * from across a room. */
export const ACTION_GLYPHS: Record<string, string> = {
  raise_setpoint: "▲",
  lower_setpoint: "▼",
  reduce_lighting: "◐",
  hold: "■",
};

export type Severity = "ok" | "warn" | "crit" | "info" | "neutral";

export function comfortSeverity(band: ComfortBand | null): Severity {
  if (!band) return "neutral";
  if (band === "comfortable") return "ok";
  if (band === "cool" || band === "warm") return "warn";
  return "crit";
}

export function airQualitySeverity(band: AirQualityBand | null): Severity {
  if (!band) return "neutral";
  return band === "good" ? "ok" : band === "moderate" ? "warn" : "crit";
}

/** Continuous colour for a PMV value, interpolating the comfort scale. Used by
 * the digital twin so a zone's temperature reads without consulting a legend. */
export function pmvColour(pmv: number | null): string {
  if (pmv === null) return "var(--color-line)";
  if (pmv <= -1.5) return "var(--color-pmv-cold)";
  if (pmv <= -0.5) return "var(--color-pmv-cool)";
  if (pmv <= 0.5) return "var(--color-pmv-good)";
  if (pmv <= 1.5) return "var(--color-pmv-warm)";
  return "var(--color-pmv-hot)";
}

export const SEVERITY_CLASSES: Record<Severity, string> = {
  ok: "text-ok bg-ok-tint border-ok/25",
  warn: "text-warn bg-warn-tint border-warn/25",
  crit: "text-crit bg-crit-tint border-crit/25",
  info: "text-info bg-info-tint border-info/25",
  neutral: "text-muted bg-sunken border-line",
};
