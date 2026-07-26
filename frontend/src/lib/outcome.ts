/**
 * What actually happened after a decision.
 *
 * The dashboard already shows what the agent expected. This closes the loop by
 * measuring the result from the same metered history, so expectation and outcome
 * sit side by side and a viewer can judge the system rather than take its word.
 *
 * The honest limitation, stated wherever this is displayed: the window is not
 * isolated. Weather, solar gain and occupancy also move across it, so the
 * measured change is what the building did, not what the decision alone caused.
 * Presenting it as attribution would be a fabricated causal claim.
 *
 * Values are averaged over several timesteps either side rather than sampled
 * once, because a single 15-minute timestep of chiller power is noisy enough to
 * produce a misleading difference.
 */

import type { Decision, Metrics } from "../api/types";

const SAMPLE_WIDTH = 4;

export interface MeasuredOutcome {
  /** True once the full window has elapsed and the comparison is meaningful. */
  complete: boolean;
  progress: number;
  coolingBeforeKw: number | null;
  coolingAfterKw: number | null;
  coolingChangePct: number | null;
  pmvBefore: number | null;
  pmvAfter: number | null;
  pmvChange: number | null;
}

function mean(values: (number | null)[]): number | null {
  const present = values.filter((value): value is number => value !== null);
  return present.length > 0
    ? present.reduce((total, value) => total + value, 0) / present.length
    : null;
}

function window(history: Metrics[], from: number, to: number): Metrics[] {
  return history.filter((sample) => sample.sequence >= from && sample.sequence <= to);
}

export function measureOutcome(
  decision: Decision | null,
  history: Metrics[],
  cadence: number,
): MeasuredOutcome | null {
  if (!decision || history.length === 0) return null;

  const at = decision.sequence;
  const latest = history[history.length - 1].sequence;
  const elapsed = latest - at;

  const before = window(history, at - SAMPLE_WIDTH + 1, at);
  if (before.length === 0) return null;

  const after = window(history, Math.max(at + 1, latest - SAMPLE_WIDTH + 1), latest);

  const coolingBefore = mean(before.map((sample) => sample.power.cooling_kw));
  const coolingAfter = after.length > 0 ? mean(after.map((s) => s.power.cooling_kw)) : null;
  const pmvBefore = mean(before.map((sample) => sample.summary.mean_pmv));
  const pmvAfter = after.length > 0 ? mean(after.map((s) => s.summary.mean_pmv)) : null;

  return {
    complete: elapsed >= cadence,
    progress: Math.min(1, Math.max(0, elapsed / cadence)),
    coolingBeforeKw: coolingBefore,
    coolingAfterKw: coolingAfter,
    // A percentage against a near-zero baseline is meaningless: overnight cooling
    // load of 0.01 kW rising to 0.02 is not a 100% increase worth reporting.
    coolingChangePct:
      coolingBefore !== null && coolingAfter !== null && coolingBefore > 0.05
        ? ((coolingAfter - coolingBefore) / coolingBefore) * 100
        : null,
    pmvBefore,
    pmvAfter,
    pmvChange:
      pmvBefore !== null && pmvAfter !== null ? pmvAfter - pmvBefore : null,
  };
}
