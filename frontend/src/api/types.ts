/**
 * The API wire contract.
 *
 * Hand-written to mirror backend/api/schemas.py rather than generated, so there
 * is no codegen step to break and the shape is readable next to the component
 * that consumes it. Every field is nullable where the backend can genuinely
 * report null -- a sensor the model does not provide reports null rather than
 * zero, and the UI must render that as "unavailable", never as a real reading.
 */

export interface Clock {
  month: number;
  day: number;
  hour: number;
  minute: number;
  label: string;
}

export type ComfortBand = "cold" | "cool" | "comfortable" | "warm" | "hot";
export type AirQualityBand = "good" | "moderate" | "poor";

export interface Zone {
  name: string;
  temperature_c: number | null;
  humidity_pct: number | null;
  occupants: number | null;
  cooling_setpoint_c: number | null;
  pmv: number | null;
  ppd_pct: number | null;
  comfort: ComfortBand | null;
  co2_ppm: number | null;
  air_quality: AirQualityBand | null;
  ventilation_kg_s: number | null;
}

export interface Power {
  cooling_kw: number | null;
  heating_kw: number | null;
  fans_kw: number | null;
  pumps_kw: number | null;
  lighting_kw: number | null;
  equipment_kw: number | null;
  total_kw: number | null;
  carbon_kg_per_hour: number | null;
}

export interface Site {
  outdoor_temperature_c: number | null;
  outdoor_humidity_pct: number | null;
  solar_w_per_m2: number | null;
}

export interface Summary {
  total_occupancy: number;
  is_occupied: boolean;
  mean_pmv: number | null;
  worst_zone: string | null;
  worst_zone_pmv: number | null;
  mean_cooling_setpoint_c: number | null;
  peak_co2_ppm: number | null;
  total_power_kw: number | null;
}

export interface Metrics {
  sequence: number;
  clock: Clock;
  zones: Zone[];
  site: Site;
  power: Power;
  summary: Summary;
}

export type ControlAction =
  | "raise_setpoint"
  | "lower_setpoint"
  | "reduce_lighting"
  | "hold";

export interface ExpectedImpact {
  cooling_change_pct: number | null;
  power_change_kw: number | null;
  comfort_change_pmv: number | null;
  carbon_change_kg_per_hour: number | null;
  summary: string;
  basis: string;
}

export interface Decision {
  sequence: number;
  clock_label: string;
  action: ControlAction;
  reasoning: string;
  observations: string[];
  source: string;
  cooling_setpoint_c: number | null;
  lighting_fraction: number | null;
  safety_adjustments: string[];
  decided_at: string;
  objective: string | null;
  impact: ExpectedImpact | null;
  /** What the deterministic policy would have chosen. Null when the rule engine
   * is itself driving -- a policy cannot meaningfully agree with itself, and the
   * UI must render null as "not applicable", never as disagreement. */
  baseline_action: ControlAction | null;
  baseline_agrees: boolean | null;
  used_fallback: boolean;
  /** The value the policy asked for, before clamping. */
  requested_setpoint_c: number | null;
}

export interface Status {
  simulation_running: boolean;
  agent_running: boolean;
  timesteps_published: number;
  decisions_taken: number;
  policy_failures: number;
  commands_submitted: number;
  commands_adjusted: number;
  policy_name: string;
  llm_latency_seconds: number | null;
  error: string | null;
  is_paused: boolean;
  variables_resolved: number;
  variables_requested: number;
  meters_resolved: number;
  meters_requested: number;
  total_energy_kwh: number;
  total_carbon_kg: number;
}

export interface ZoneGeometry {
  name: string;
  footprint: [number, number][];
  area_m2: number;
  centroid: [number, number];
  is_core: boolean;
  orientation: string | null;
  azimuth_deg: number | null;
}

export interface Geometry {
  zones: ZoneGeometry[];
  bounds: [number, number, number, number];
  width_m: number;
  depth_m: number;
  floor_area_m2: number;
  carbon_basis: string;
}

export interface SafetyLimits {
  min_cooling_setpoint_c: number;
  max_cooling_setpoint_c: number;
  min_heating_setpoint_c: number;
  max_heating_setpoint_c: number;
  min_deadband_c: number;
  min_lighting_fraction: number;
  max_lighting_fraction: number;
  max_setpoint_change_c: number;
}

export interface Config {
  model_name: string;
  policy: string;
  llm_model: string;
  seconds_per_timestep: number;
  timesteps_per_decision: number;
  start_date: string;
  zones: string[];
  limits: SafetyLimits;
  tuning: Record<string, number>;
}

export interface AppliedCommand {
  accepted: boolean;
  action: ControlAction;
  cooling_setpoint_c: number | null;
  heating_setpoint_c: number | null;
  lighting_fraction: number | null;
  safety_adjustments: string[];
}

export interface Report {
  headline: string;
  period: Record<string, number | string>;
  energy: Record<string, number | null>;
  comfort: Record<string, number | string | null>;
  agent: Record<string, unknown>;
  savings: Record<string, number | string | null>;
  markdown: string;
}

/** Server pushes. `snapshot` seeds a new connection; `update` carries only what
 * the client has not seen, keyed by sequence. */
export type StreamMessage =
  | { type: "snapshot"; status: Status; history: Metrics[]; decisions: Decision[] }
  | { type: "update"; status: Status; metrics: Metrics[]; decisions: Decision[] };

export type ConnectionState = "connecting" | "live" | "reconnecting" | "offline";
