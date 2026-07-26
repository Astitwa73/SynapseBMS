/**
 * The building, drawn from its own geometry.
 *
 * Polygons come from the FLOOR surfaces of the EnergyPlus model, so this is the
 * actual plan being simulated: four trapezoidal perimeter zones wrapping a
 * rectangular core, oriented by the outward normals of their exterior walls.
 * Anyone who works with building models will recognise the five-zone layout, and
 * a decorative rectangle in its place would read as a mock-up.
 *
 * Fill colour is PMV, so thermal state is readable without consulting a legend.
 * Occupancy is drawn as discrete marks rather than a number, because "is anyone
 * in there" is the question the plan should answer at a glance.
 */

import { motion } from "framer-motion";
import { useState } from "react";
import type { Geometry, Metrics, Zone, ZoneGeometry } from "../../api/types";
import { integer, number, pmvColour, signed } from "../../lib/format";
import { AwaitingData } from "../ui/primitives";

// Metres, not pixels: the viewBox is in model units. Generous enough for the
// compass and the zone labels, small enough that the building fills the frame.
const PADDING = 2.5;
const COMPASS_ROOM = 5;
const MAX_OCCUPANT_MARKS = 12;

export function FloorPlan({
  geometry,
  metrics,
  highlightZone,
}: {
  geometry: Geometry | null;
  metrics: Metrics | null;
  /** The zone the agent named in its current decision, outlined so the reader
   * can connect the reasoning to a place in the building. */
  highlightZone: string | null;
}) {
  const [hovered, setHovered] = useState<string | null>(null);

  if (!geometry) return <AwaitingData label="Loading building geometry" />;

  const [minX, minY, maxX, maxY] = geometry.bounds;
  const width = maxX - minX;
  const depth = maxY - minY;

  const readings = new Map<string, Zone>(
    (metrics?.zones ?? []).map((zone) => [zone.name, zone]),
  );
  const active = hovered ?? highlightZone;
  const activeZone = active ? readings.get(active) : undefined;

  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <svg
        viewBox={`${minX - PADDING} ${minY - PADDING} ${width + PADDING * 2} ${depth + PADDING + COMPASS_ROOM}`}
        className="min-h-0 w-full flex-1"
        // EnergyPlus uses +Y as north; SVG grows downward, so the plan is
        // flipped to keep north at the top where a reader expects it.
        style={{ transform: "scaleY(-1)" }}
        role="img"
        aria-label="Building floor plan with live zone comfort"
      >
        {geometry.zones.map((zone) => (
          <ZoneShape
            key={zone.name}
            zone={zone}
            reading={readings.get(zone.name)}
            isActive={active === zone.name}
            dimmed={active !== null && active !== zone.name}
            onHover={setHovered}
          />
        ))}
        <CompassRose x={minX + 1.5} y={maxY + 4} />
      </svg>

      <ZoneDetail
        geometry={geometry.zones.find((zone) => zone.name === active) ?? null}
        reading={activeZone ?? null}
      />
    </div>
  );
}

function ZoneShape({
  zone,
  reading,
  isActive,
  dimmed,
  onHover,
}: {
  zone: ZoneGeometry;
  reading: Zone | undefined;
  isActive: boolean;
  dimmed: boolean;
  onHover: (name: string | null) => void;
}) {
  const points = zone.footprint.map(([x, y]) => `${x},${y}`).join(" ");
  const [cx, cy] = zone.centroid;
  const pmv = reading?.pmv ?? null;
  const occupants = Math.round(reading?.occupants ?? 0);

  return (
    <g
      onMouseEnter={() => onHover(zone.name)}
      onMouseLeave={() => onHover(null)}
      className="cursor-help"
    >
      <motion.polygon
        points={points}
        animate={{
          fill: pmvColour(pmv),
          fillOpacity: dimmed ? 0.25 : pmv === null ? 0.15 : 0.55,
        }}
        transition={{ duration: 0.6 }}
        stroke={isActive ? "var(--color-brand)" : "var(--color-ink)"}
        strokeWidth={isActive ? 0.6 : 0.25}
        strokeLinejoin="round"
      />

      {/* Counter-flipped so text is upright inside the mirrored plan. */}
      <g transform={`translate(${cx} ${cy}) scale(1 -1)`}>
        <text
          textAnchor="middle"
          y={-2.2}
          className="fill-ink font-semibold"
          style={{ fontSize: 2.1 }}
        >
          {zone.is_core ? "CORE" : zone.orientation}
        </text>
        <text
          textAnchor="middle"
          y={0.8}
          className="tabular fill-ink font-bold"
          style={{ fontSize: 3 }}
        >
          {reading?.temperature_c !== null && reading?.temperature_c !== undefined
            ? `${reading.temperature_c.toFixed(1)}°`
            : "—"}
        </text>
        <OccupantMarks count={occupants} />
      </g>
    </g>
  );
}

/** One mark per occupant up to a cap, then a count. Discrete marks make arrival
 * and departure visible as a change in density rather than a changing digit. */
function OccupantMarks({ count }: { count: number }) {
  if (count === 0) return null;

  const shown = Math.min(count, MAX_OCCUPANT_MARKS);
  const spacing = 1.15;
  const startX = -((shown - 1) * spacing) / 2;

  return (
    <g>
      {Array.from({ length: shown }, (_, index) => (
        <motion.circle
          key={index}
          initial={{ opacity: 0, r: 0 }}
          animate={{ opacity: 0.85, r: 0.42 }}
          transition={{ delay: index * 0.03, duration: 0.25 }}
          cx={startX + index * spacing}
          cy={3.1}
          className="fill-ink"
        />
      ))}
      {count > MAX_OCCUPANT_MARKS && (
        <text
          x={0}
          y={5.4}
          textAnchor="middle"
          className="tabular fill-muted"
          style={{ fontSize: 1.7 }}
        >
          {count}
        </text>
      )}
    </g>
  );
}

function CompassRose({ x, y }: { x: number; y: number }) {
  return (
    <g transform={`translate(${x} ${y}) scale(1 -1)`} aria-hidden="true">
      <line x1="0" y1="0" x2="0" y2="-5" className="stroke-line-strong" strokeWidth="0.3" />
      <path d="M-1 -4 L0 -5.6 L1 -4 Z" className="fill-line-strong" />
      <text
        x="0"
        y="2"
        textAnchor="middle"
        className="fill-faint font-semibold"
        style={{ fontSize: 2.2 }}
      >
        N
      </text>
    </g>
  );
}

/** Detail for the hovered or agent-referenced zone. Kept out of the plan so the
 * plan stays readable, and pinned so the layout does not jump on hover. */
function ZoneDetail({
  geometry,
  reading,
}: {
  geometry: ZoneGeometry | null;
  reading: Zone | null;
}) {
  if (!geometry) {
    return (
      <p className="shrink-0 border-t border-line pt-2 text-[11px] text-faint">
        Hover a zone for detail. Fill colour is PMV comfort; dots are occupants.
      </p>
    );
  }

  const cells: [string, string][] = [
    ["Temp", number(reading?.temperature_c, 1, "°C")],
    ["Setpoint", number(reading?.cooling_setpoint_c, 1, "°C")],
    ["PMV", signed(reading?.pmv ?? null)],
    ["PPD", number(reading?.ppd_pct, 0, "%")],
    ["RH", number(reading?.humidity_pct, 0, "%")],
    ["CO₂", `${integer(reading?.co2_ppm ?? null)} ppm`],
    ["Occupants", integer(reading?.occupants ?? null)],
    ["Area", number(geometry.area_m2, 0, "m²")],
  ];

  return (
    <div className="shrink-0 border-t border-line pt-2">
      <div className="mb-1 flex items-baseline gap-2">
        <span className="text-xs font-bold text-ink">{geometry.name}</span>
        <span className="text-[10px] uppercase tracking-[0.07em] text-faint">
          {geometry.is_core
            ? "core zone · no exterior wall"
            : `perimeter · faces ${geometry.orientation}`}
        </span>
        {reading?.comfort && (
          <span className="ml-auto text-[10px] font-medium text-muted">
            {reading.comfort}
          </span>
        )}
      </div>
      <dl className="grid grid-cols-4 gap-x-2 gap-y-0.5">
        {cells.map(([label, value]) => (
          <div key={label} className="min-w-0">
            <dt className="text-[9px] uppercase tracking-[0.06em] text-faint">{label}</dt>
            <dd className="tabular truncate text-[11px] font-semibold text-ink">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
