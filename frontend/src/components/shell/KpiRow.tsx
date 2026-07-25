/**
 * The six figures a judge should be able to read from across a room.
 *
 * Each carries its own severity so the row communicates building health before
 * any number is read. Sparklines are drawn from real history rather than being
 * decorative, and appear only where a trend is meaningful.
 */

import { motion } from "framer-motion";
import type { Metrics, Status } from "../../api/types";
import {
  airQualitySeverity,
  comfortSeverity,
  integer,
  number,
  percent,
  signed,
  type Severity,
} from "../../lib/format";
import { Readout } from "../ui/primitives";

interface Props {
  metrics: Metrics | null;
  history: Metrics[];
  status: Status | null;
  carbonBasis: string | null;
  estimatedSavingPct: number | null;
}

export function KpiRow({
  metrics,
  history,
  status,
  carbonBasis,
  estimatedSavingPct,
}: Props) {
  const summary = metrics?.summary;
  const pmv = summary?.mean_pmv ?? null;
  const co2 = summary?.peak_co2_ppm ?? null;

  const comfortBand =
    pmv === null
      ? null
      : pmv < -1.5
        ? "cold"
        : pmv < -0.5
          ? "cool"
          : pmv <= 0.5
            ? "comfortable"
            : pmv <= 1.5
              ? "warm"
              : "hot";

  const airBand =
    co2 === null ? null : co2 < 800 ? "good" : co2 < 1100 ? "moderate" : "poor";

  const occupancyRatio =
    summary && summary.total_occupancy > 0 ? summary.total_occupancy / 52 : 0;

  return (
    <div className="grid shrink-0 grid-cols-2 gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-3 xl:grid-cols-6">
      <Tile
        label="Current power"
        value={number(summary?.total_power_kw ?? null, 1)}
        unit="kW"
        hint={`cooling ${number(metrics?.power.cooling_kw ?? null, 1, "kW")}`}
        spark={history.map((m) => m.summary.total_power_kw ?? 0)}
      />

      <Tile
        label="Est. cooling saved"
        value={estimatedSavingPct === null ? "—" : percent(estimatedSavingPct)}
        hint="vs unmanaged baseline"
        severity={estimatedSavingPct && estimatedSavingPct > 0 ? "ok" : "neutral"}
        title="Estimated from setpoint offset at a sensitivity measured in compare_policies.py, and capped. Not a live counterfactual."
      />

      <Tile
        label="Comfort (PMV)"
        value={signed(pmv)}
        hint={comfortBand ?? "no occupied zones"}
        severity={comfortSeverity(comfortBand as never)}
        spark={history.map((m) => m.summary.mean_pmv ?? 0)}
      />

      <Tile
        label="Occupancy"
        value={integer(summary?.total_occupancy ?? null)}
        unit="people"
        hint={summary?.is_occupied ? percent(occupancyRatio * 100) + " of design" : "unoccupied"}
        severity={summary?.is_occupied ? "info" : "neutral"}
      />

      <Tile
        label="Air quality"
        value={integer(co2)}
        unit="ppm"
        hint={airBand ? `${airBand} · peak zone` : "—"}
        severity={airQualitySeverity(airBand as never)}
      />

      <Tile
        label="Carbon"
        value={number(status?.total_carbon_kg ?? null, 1)}
        unit="kg CO₂e"
        hint={`${number(status?.total_energy_kwh ?? null, 0, "kWh")} this run`}
        title={carbonBasis ?? undefined}
      />
    </div>
  );
}

function Tile({
  label,
  value,
  unit,
  hint,
  severity = "neutral",
  spark,
  title,
}: {
  label: string;
  value: string;
  unit?: string;
  hint?: string;
  severity?: Severity;
  spark?: number[];
  title?: string;
}) {
  return (
    <div className="relative bg-surface px-4 py-3" title={title}>
      <Readout label={label} value={value} unit={unit} hint={hint} severity={severity} />
      {spark && spark.length > 3 && (
        <Sparkline values={spark} severity={severity} />
      )}
      {title && (
        <span
          className="absolute right-2 top-2 grid h-3.5 w-3.5 place-items-center rounded-full border border-line text-[9px] font-bold text-faint"
          aria-hidden="true"
        >
          i
        </span>
      )}
    </div>
  );
}

/** Trend only. No axes, no labels: it exists to show direction and volatility,
 * and anything more would compete with the charts below. */
function Sparkline({ values, severity }: { values: number[]; severity: Severity }) {
  const recent = values.slice(-60);
  const min = Math.min(...recent);
  const max = Math.max(...recent);
  const span = max - min || 1;

  const points = recent
    .map((value, index) => {
      const x = (index / Math.max(1, recent.length - 1)) * 100;
      const y = 100 - ((value - min) / span) * 100;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  const stroke =
    severity === "ok"
      ? "var(--color-ok)"
      : severity === "warn"
        ? "var(--color-warn)"
        : severity === "crit"
          ? "var(--color-crit)"
          : "var(--color-line-strong)";

  return (
    <svg
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      className="mt-1.5 h-5 w-full"
      aria-hidden="true"
    >
      <motion.polyline
        points={points}
        fill="none"
        stroke={stroke}
        strokeWidth="2.5"
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
        initial={false}
      />
    </svg>
  );
}
