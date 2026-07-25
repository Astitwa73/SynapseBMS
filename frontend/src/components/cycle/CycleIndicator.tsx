/**
 * The autonomous loop, always on screen.
 *
 * This is the legend for the entire dashboard and simultaneously a live status
 * readout. A viewer learns the model of the system on the first pass and has it
 * confirmed on every pass after, which is what makes the interface
 * self-explanatory without narration.
 *
 * Purely presentational: it renders whatever phase useDecisionCycle reports and
 * owns no timing of its own.
 */

import { motion } from "framer-motion";
import {
  CYCLE_PHASES,
  PHASE_DESCRIPTIONS,
  PHASE_LABELS,
  type CyclePhase,
  type DecisionCycle,
} from "../../hooks/useDecisionCycle";
import { seconds } from "../../lib/format";

const ORDER: Record<string, number> = Object.fromEntries(
  CYCLE_PHASES.map((phase, index) => [phase, index]),
);

export function CycleIndicator({ cycle }: { cycle: DecisionCycle }) {
  const activeIndex = cycle.phase === "idle" ? -1 : ORDER[cycle.phase];

  return (
    <div className="flex items-center gap-3">
      <div className="flex items-center gap-1">
        {CYCLE_PHASES.map((phase, index) => (
          <PhaseStep
            key={phase}
            phase={phase}
            index={index}
            activeIndex={activeIndex}
            progress={cycle.progress}
            isLast={index === CYCLE_PHASES.length - 1}
          />
        ))}
      </div>

      {/* Real model latency, shown rather than hidden behind a spinner: it is
          the moment a viewer realises a language model is actually running. */}
      {cycle.isThinking && (
        <motion.span
          initial={{ opacity: 0, x: -4 }}
          animate={{ opacity: 1, x: 0 }}
          className="tabular shrink-0 rounded border border-brand/30 bg-brand-tint px-2 py-0.5 text-[11px] font-semibold text-brand-dark"
        >
          {seconds(cycle.reasoningMs)}
        </motion.span>
      )}
    </div>
  );
}

function PhaseStep({
  phase,
  index,
  activeIndex,
  progress,
  isLast,
}: {
  phase: Exclude<CyclePhase, "idle">;
  index: number;
  activeIndex: number;
  progress: number | null;
  isLast: boolean;
}) {
  const isActive = index === activeIndex;
  const isDone = activeIndex >= 0 && index < activeIndex;

  return (
    <div className="flex items-center gap-1" title={PHASE_DESCRIPTIONS[phase]}>
      <div
        className={`relative flex items-center gap-1.5 rounded px-2 py-1 transition-colors duration-300 ${
          isActive
            ? "bg-brand text-white"
            : isDone
              ? "text-muted"
              : "text-faint"
        }`}
      >
        <span
          className={`h-1.5 w-1.5 shrink-0 rounded-full transition-colors duration-300 ${
            isActive ? "bg-white" : isDone ? "bg-line-strong" : "bg-line"
          }`}
        />
        <span className="text-[11px] font-semibold uppercase tracking-[0.07em]">
          {PHASE_LABELS[phase]}
        </span>

        {/* Fills only for the stages with a fixed duration. Open-ended stages
            deliberately show no progress bar, because inventing one would imply
            a completion time the system does not know. */}
        {isActive && progress !== null && (
          <motion.span
            className="absolute inset-x-0 bottom-0 h-0.5 origin-left rounded-b bg-white/70"
            style={{ scaleX: progress }}
          />
        )}
      </div>

      {!isLast && (
        <svg width="12" height="8" viewBox="0 0 12 8" aria-hidden="true">
          <path
            d="M0 4 H9 M6 1.5 L9 4 L6 6.5"
            fill="none"
            strokeWidth="1.25"
            strokeLinecap="round"
            strokeLinejoin="round"
            className={
              isDone || (isActive && index < activeIndex)
                ? "stroke-line-strong"
                : "stroke-line"
            }
          />
        </svg>
      )}
    </div>
  );
}

/** The loop closes: RESPOND feeds the next OBSERVE. Drawn as a caption rather
 * than a curved arrow because a wrapping line in a header row reads as clutter,
 * and the sentence carries the same information. */
export function CycleCaption({ cycle }: { cycle: DecisionCycle }) {
  const text =
    cycle.phase === "idle"
      ? "Waiting for the first decision"
      : PHASE_DESCRIPTIONS[cycle.phase as Exclude<CyclePhase, "idle">];

  return (
    <motion.p
      key={cycle.phase}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.25 }}
      className="text-xs text-muted"
    >
      {text}
    </motion.p>
  );
}
