/**
 * Trends over the run, with decision markers.
 *
 * One chart with a metric selector rather than a wall of small charts: at this
 * panel size four thumbnails are unreadable, and the vertical rules marking each
 * decision are what make the chart worth showing at all. Seeing the curve bend
 * after a marker is the closed loop rendered.
 */

import { useMemo } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Decision, Metrics } from "../../api/types";

type MetricKey = "power" | "temperature" | "comfort";

const SERIES: Record<
  MetricKey,
  { label: string; unit: string; lines: { key: string; name: string; colour: string }[] }
> = {
  power: {
    label: "Power",
    unit: "kW",
    lines: [
      { key: "total", name: "Total", colour: "var(--color-ink)" },
      { key: "cooling", name: "Cooling", colour: "var(--color-info)" },
      { key: "lighting", name: "Lighting", colour: "var(--color-warn)" },
    ],
  },
  temperature: {
    label: "Temperature",
    unit: "°C",
    lines: [
      { key: "indoor", name: "Indoor", colour: "var(--color-ink)" },
      { key: "setpoint", name: "Setpoint", colour: "var(--color-brand)" },
      { key: "outdoor", name: "Outdoor", colour: "var(--color-info)" },
    ],
  },
  comfort: {
    label: "Comfort",
    unit: "PMV",
    lines: [{ key: "pmv", name: "Mean PMV", colour: "var(--color-ok)" }],
  },
};

export type { MetricKey };
export const METRIC_KEYS = Object.keys(SERIES) as MetricKey[];
export const METRIC_LABELS = Object.fromEntries(
  METRIC_KEYS.map((key) => [key, SERIES[key].label]),
) as Record<MetricKey, string>;

export function TrendChart({
  history,
  decisions,
  metric,
}: {
  history: Metrics[];
  decisions: Decision[];
  metric: MetricKey;
}) {

  const data = useMemo(
    () =>
      history.map((sample) => ({
        sequence: sample.sequence,
        label: sample.clock.label.slice(6),
        total: sample.power.total_kw,
        cooling: sample.power.cooling_kw,
        lighting: sample.power.lighting_kw,
        indoor:
          sample.zones.reduce((sum, z) => sum + (z.temperature_c ?? 0), 0) /
          (sample.zones.filter((z) => z.temperature_c !== null).length || 1),
        setpoint: sample.summary.mean_cooling_setpoint_c,
        outdoor: sample.site.outdoor_temperature_c,
        pmv: sample.summary.mean_pmv,
      })),
    [history],
  );

  // Only markers inside the visible window; the history buffer is bounded, so an
  // older decision has no x position to sit on.
  const first = data[0]?.sequence ?? 0;
  const markers = decisions.filter((d) => d.sequence >= first).slice(-12);
  const config = SERIES[metric];

  // Sequence, not clock label, is the x axis. "14:30" repeats every simulated
  // day, so a categorical axis cannot place a decision marker unambiguously and
  // silently drops it.
  const labels = useMemo(
    () => new Map(data.map((point) => [point.sequence, point.label])),
    [data],
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-x-3">
        {config.lines.map((line) => (
          <span key={line.key} className="flex items-center gap-1 text-[10px] text-muted">
            <span className="h-0.5 w-3 rounded-full" style={{ backgroundColor: line.colour }} />
            {line.name}
          </span>
        ))}
      </div>

      <div className="min-h-0 flex-1">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -22 }}>
            <CartesianGrid stroke="var(--color-line)" strokeDasharray="2 3" vertical={false} />
            <XAxis
              dataKey="sequence"
              type="number"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(value: number) => labels.get(value) ?? ""}
              tick={{ fontSize: 9, fill: "var(--color-faint)" }}
              minTickGap={44}
              stroke="var(--color-line-strong)"
            />
            <YAxis
              tick={{ fontSize: 9, fill: "var(--color-faint)" }}
              stroke="var(--color-line-strong)"
              width={44}
            />
            <Tooltip
              contentStyle={{
                fontSize: 11,
                borderRadius: 6,
                border: "1px solid var(--color-line)",
                padding: "4px 8px",
              }}
              labelFormatter={(value) => labels.get(Number(value)) ?? ""}
              formatter={(value, name) => [
                typeof value === "number" ? `${value.toFixed(2)} ${config.unit}` : "—",
                String(name),
              ]}
            />

            {markers.map((decision) => (
              <ReferenceLine
                key={`${decision.sequence}-${decision.decided_at}`}
                x={decision.sequence}
                stroke={
                  decision.safety_adjustments.length > 0
                    ? "var(--color-warn)"
                    : "var(--color-brand)"
                }
                strokeWidth={1}
                strokeOpacity={0.45}
              />
            ))}

            {config.lines.map((line) => (
              <Line
                key={line.key}
                type="monotone"
                dataKey={line.key}
                name={line.name}
                stroke={line.colour}
                strokeWidth={1.6}
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
