/**
 * Where every number on this dashboard comes from.
 *
 * Three categories, never mixed, because a figure presented with more authority
 * than it has is worse than no figure at all.
 *
 *   MEASURED   read directly from the simulation's own output
 *   DERIVED    computed from measured values through a stated model
 *   ESTIMATED  projected beyond what was measured, with a stated basis
 *
 * The whole building is simulated, which is stated once in the interface rather
 * than caveated on every tile. Within that frame, "measured" means EnergyPlus
 * reported it and "derived" means we computed it.
 *
 * PMV is Derived, not Measured, and this is the distinction most worth getting
 * right: the Fanger model takes six inputs and this building supplies two. The
 * other four are assumptions, and a reader is entitled to see them.
 */

export type Provenance = "measured" | "derived" | "estimated";

export const PROVENANCE_LABELS: Record<Provenance, string> = {
  measured: "Measured",
  derived: "Derived",
  estimated: "Estimated",
};

export const PROVENANCE_CLASSES: Record<Provenance, string> = {
  measured: "border-ok/30 bg-ok-tint text-ok",
  derived: "border-info/30 bg-info-tint text-info",
  estimated: "border-warn/30 bg-warn-tint text-warn",
};

export interface Basis {
  provenance: Provenance;
  /** Shown on hover. States the model or the assumption, never just the source. */
  detail: string;
}

const COMFORT_ASSUMPTIONS =
  "Fanger PMV (ISO 7730) from measured air temperature and relative humidity. " +
  "Four of six model inputs are assumptions: mean radiant temperature equal to " +
  "air temperature, air velocity 0.1 m/s, metabolic rate 1.1 met, clothing 0.5 clo.";

export const BASIS: Record<string, Basis> = {
  temperature: {
    provenance: "measured",
    detail: "Zone Mean Air Temperature, reported by EnergyPlus each timestep.",
  },
  humidity: {
    provenance: "measured",
    detail: "Zone Air Relative Humidity, reported by EnergyPlus each timestep.",
  },
  occupancy: {
    provenance: "measured",
    detail:
      "Zone People Occupant Count. The occupancy schedule is part of the building " +
      "model, so this is the simulation's own value rather than a sensor reading.",
  },
  power: {
    provenance: "measured",
    detail:
      "Electricity meters: Building + HVAC + Plant, the disjoint system-category " +
      "meters. Cooling is metered under Plant in this model's chilled-water loop.",
  },
  setpoint: {
    provenance: "measured",
    detail: "Zone Thermostat Cooling Setpoint Temperature, read back after actuation.",
  },
  ventilation: {
    provenance: "measured",
    detail: "Zone Mechanical Ventilation Mass Flow Rate.",
  },
  latency: {
    provenance: "measured",
    detail: "Wall-clock time for the model to answer, timed per request.",
  },
  pmv: { provenance: "derived", detail: COMFORT_ASSUMPTIONS },
  ppd: {
    provenance: "derived",
    detail:
      "Predicted Percentage Dissatisfied, computed from PMV. Bottoms out at 5% by " +
      "construction: some dissatisfaction exists even at thermal neutrality.",
  },
  co2: {
    provenance: "derived",
    detail:
      "Steady-state mass balance from occupant count and mechanical ventilation " +
      "flow. This model does not simulate contaminants, so CO2 is computed rather " +
      "than read. Being steady-state, it shows equilibrium rather than the ramp as " +
      "a room fills.",
  },
  impact: {
    provenance: "derived",
    detail:
      "Projected from the chosen action using a cooling sensitivity of 17.2% per " +
      "degree measured in compare_policies.py, and the Fanger curve at 0.33 PMV " +
      "per degree.",
  },
  objective: {
    provenance: "derived",
    detail:
      "Read from the action and the current building state, not produced by the " +
      "language model.",
  },
  outcome: {
    provenance: "measured",
    detail:
      "The actual change in metered cooling power and derived comfort over the " +
      "window following the decision. Not isolated: weather and occupancy also " +
      "change across the window, so this is what happened, not what the decision " +
      "alone caused.",
  },
  savings: {
    provenance: "estimated",
    detail:
      "Projected from the setpoint offset against the unmanaged baseline at a " +
      "measured sensitivity, and capped. There is no live counterfactual — the " +
      "building cannot be run both ways at once — so this is an estimate, not a " +
      "measurement. The measured figure is in the benchmark panel.",
  },
  carbon: {
    provenance: "estimated",
    detail:
      "Metered electricity at a fixed grid factor of 0.40 kg CO2e/kWh (US eGRID " +
      "average). A fixed factor means carbon scales directly with energy and " +
      "carries no independent information.",
  },
  benchmark: {
    provenance: "measured",
    detail:
      "Measured by scripts/compare_policies.py: the same simulated day run with no " +
      "agent, the rule engine, and the language model, with decisions made " +
      "synchronously so every policy gets identical opportunities.",
  },
};
