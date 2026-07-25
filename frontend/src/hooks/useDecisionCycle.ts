/**
 * The autonomous loop, as a state machine.
 *
 * Orchestration only: this hook decides which stage of Observe -> Reason ->
 * Decide -> Validate -> Act -> Respond the system is in, and every component
 * merely renders that. Keeping the choreography here means presentation
 * components stay pure and the timing lives in one auditable place.
 *
 * Two of the six stages have real, not chosen, durations:
 *
 *   REASON  runs from the moment the backend is due to decide until the decision
 *           actually arrives. That is genuinely how long the language model took,
 *           which is why it is shown rather than hidden behind a spinner.
 *   RESPOND runs until the next decision is due, which is the building actually
 *           reacting to what was applied.
 *
 * The other four are short, fixed beats whose only job is to make a causal chain
 * legible at human speed.
 */

import { useEffect, useReducer, useRef, useState } from "react";
import type { Decision, Metrics } from "../api/types";

export type CyclePhase =
  | "idle"
  | "observe"
  | "reason"
  | "decide"
  | "validate"
  | "act"
  | "respond";

export const CYCLE_PHASES: Exclude<CyclePhase, "idle">[] = [
  "observe",
  "reason",
  "decide",
  "validate",
  "act",
  "respond",
];

export const PHASE_LABELS: Record<Exclude<CyclePhase, "idle">, string> = {
  observe: "Observe",
  reason: "Reason",
  decide: "Decide",
  validate: "Validate",
  act: "Act",
  respond: "Respond",
};

export const PHASE_DESCRIPTIONS: Record<Exclude<CyclePhase, "idle">, string> = {
  observe: "Reading zone comfort, occupancy and load from the simulation",
  reason: "The policy is choosing an action for the current building state",
  decide: "An action and its justification have been produced",
  validate: "The safety layer is checking the command against its limits",
  act: "The applied setpoint is being written to the building",
  respond: "The building is reacting; sensors report the result",
};

/** Fixed beats, in ms. Long enough to read, short enough not to lag reality. */
const BEATS: Record<"decide" | "validate" | "act" | "observe", number> = {
  observe: 600,
  decide: 900,
  validate: 1300,
  act: 700,
};

interface CycleState {
  phase: CyclePhase;
  since: number;
}

export interface DecisionCycle extends CycleState {
  /** Milliseconds spent in REASON so far. Real model latency, not a guess. */
  reasoningMs: number;
  isThinking: boolean;
  /** 0..1 through the current stage, or null where duration is event-driven. */
  progress: number | null;
}

function reducer(_state: CycleState, phase: CyclePhase): CycleState {
  return { phase, since: Date.now() };
}

interface Options {
  history: Metrics[];
  decisions: Decision[];
  decisionEpoch: number;
  /** Timesteps between decisions, from /api/config. */
  cadence: number;
}

export function useDecisionCycle({
  history,
  decisions,
  decisionEpoch,
  cadence,
}: Options): DecisionCycle {
  const [state, setPhase] = useReducer(reducer, { phase: "idle", since: Date.now() });
  const [now, setNow] = useState(() => Date.now());
  const timers = useRef<number[]>([]);

  const clearTimers = () => {
    timers.current.forEach(window.clearTimeout);
    timers.current = [];
  };

  const schedule = (phase: CyclePhase, delay: number) => {
    timers.current.push(window.setTimeout(() => setPhase(phase), delay));
  };

  const phaseRef = useRef<CyclePhase>("idle");
  phaseRef.current = state.phase;

  // A decision has landed: walk the consequence stages, then settle into
  // RESPOND, where the building is genuinely reacting.
  //
  // A deterministic policy answers in the same frame the sequence boundary is
  // crossed, so OBSERVE and REASON would never be seen. The system does still
  // observe -- it just takes microseconds -- so the observe beat is played here
  // when it has not already run. REASON is not synthesised: a policy that does
  // not deliberate does not get a deliberation stage.
  useEffect(() => {
    if (decisionEpoch === 0 || decisions.length === 0) return;

    const alreadyObserved =
      phaseRef.current === "reason" || phaseRef.current === "observe";
    const lead = alreadyObserved ? 0 : BEATS.observe;

    clearTimers();
    if (!alreadyObserved) setPhase("observe");

    schedule("decide", lead);
    schedule("validate", lead + BEATS.decide);
    schedule("act", lead + BEATS.decide + BEATS.validate);
    schedule("respond", lead + BEATS.decide + BEATS.validate + BEATS.act);

    return clearTimers;
  }, [decisionEpoch]); // eslint-disable-line react-hooks/exhaustive-deps

  // The simulation has advanced far enough that the next decision is due, so the
  // policy is now working. Show OBSERVE briefly, then hold REASON until the
  // decision actually arrives.
  const latestSequence = history.length > 0 ? history[history.length - 1].sequence : 0;
  const lastDecisionSequence =
    decisions.length > 0 ? decisions[decisions.length - 1].sequence : 0;
  const decisionIsDue =
    latestSequence > 0 && latestSequence - lastDecisionSequence >= cadence;

  useEffect(() => {
    if (!decisionIsDue) return;
    if (state.phase === "observe" || state.phase === "reason") return;

    clearTimers();
    setPhase("observe");
    schedule("reason", BEATS.observe);

    return clearTimers;
  }, [decisionIsDue]); // eslint-disable-line react-hooks/exhaustive-deps

  // A single ticker drives every elapsed readout. Running one timer here rather
  // than one per component keeps re-renders proportional to the clock, not to
  // the number of things displaying it.
  const isThinking = state.phase === "reason";
  useEffect(() => {
    if (!isThinking && state.phase !== "respond") return;
    const id = window.setInterval(() => setNow(Date.now()), 100);
    return () => window.clearInterval(id);
  }, [isThinking, state.phase]);

  const elapsed = now - state.since;
  const beat = BEATS[state.phase as keyof typeof BEATS];

  return {
    phase: state.phase,
    since: state.since,
    reasoningMs: isThinking ? Math.max(0, elapsed) : 0,
    isThinking,
    progress: beat ? Math.min(1, elapsed / beat) : null,
  };
}
