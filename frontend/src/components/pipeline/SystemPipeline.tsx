/**
 * The architecture, animating as work flows through it.
 *
 * Each stage lights when that part of the system is genuinely doing something,
 * derived from the decision cycle rather than on a decorative timer. The purpose
 * is to make the closed loop legible: EnergyPlus feeds sensors, sensors feed
 * shared state, the agent reads it, the decision engine validates, control writes
 * back into EnergyPlus.
 *
 * MCP is shown as a branch rather than a link in the chain, because that is what
 * it is: an external interface onto the same state and the same control path,
 * not a step the control loop passes through.
 */

import { motion } from "framer-motion";
import type { CyclePhase } from "../../hooks/useDecisionCycle";

interface Stage {
  id: string;
  label: string;
  detail: string;
  /** Cycle phases during which this stage is doing work. */
  activeDuring: CyclePhase[];
}

const STAGES: Stage[] = [
  {
    id: "energyplus",
    label: "EnergyPlus",
    detail: "Physics simulation, 15-minute timesteps",
    activeDuring: ["respond", "act"],
  },
  {
    id: "sensors",
    label: "Sensors",
    detail: "38 output variables, 9 meters",
    activeDuring: ["observe", "respond"],
  },
  {
    id: "state",
    label: "Shared State",
    detail: "Immutable snapshots, sequence-numbered",
    activeDuring: ["observe"],
  },
  {
    id: "llm",
    label: "LLM Agent",
    detail: "Llama 3 selects one action",
    activeDuring: ["reason", "decide"],
  },
  {
    id: "decision",
    label: "Decision Engine",
    detail: "Safety envelope, clamping, rate limit",
    activeDuring: ["validate"],
  },
  {
    id: "control",
    label: "Control",
    detail: "Actuators written before the predictor",
    activeDuring: ["act"],
  },
];

export function SystemPipeline({ phase }: { phase: CyclePhase }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-stretch gap-1.5 overflow-x-auto pb-1">
        {STAGES.map((stage, index) => (
          <PipelineStage
            key={stage.id}
            stage={stage}
            phase={phase}
            isLast={index === STAGES.length - 1}
          />
        ))}
      </div>

      <div className="flex items-center gap-2 pl-1">
        <ReturnPath />
        <span className="text-[10px] uppercase tracking-[0.08em] text-faint">
          Control writes back into EnergyPlus — the loop is closed
        </span>
        <span className="ml-auto flex items-center gap-1.5 rounded border border-line bg-sunken px-1.5 py-0.5 text-[10px] text-muted">
          <span className="h-1 w-1 rounded-full bg-info" />
          MCP exposes the same state and control path to external clients
        </span>
      </div>
    </div>
  );
}

function PipelineStage({
  stage,
  phase,
  isLast,
}: {
  stage: Stage;
  phase: CyclePhase;
  isLast: boolean;
}) {
  const isActive = stage.activeDuring.includes(phase);

  return (
    <div className="flex flex-1 items-center gap-1.5" title={stage.detail}>
      <motion.div
        animate={{
          backgroundColor: isActive ? "var(--color-brand-tint)" : "var(--color-surface)",
          borderColor: isActive ? "var(--color-brand)" : "var(--color-line)",
        }}
        transition={{ duration: 0.25 }}
        className="min-w-0 flex-1 rounded border px-2 py-1.5"
      >
        <div className="flex items-center gap-1.5">
          <motion.span
            animate={{ scale: isActive ? 1 : 0.7, opacity: isActive ? 1 : 0.35 }}
            transition={{ duration: 0.25 }}
            className="h-1.5 w-1.5 shrink-0 rounded-full bg-brand"
          />
          <span
            className={`truncate text-[11px] font-semibold transition-colors duration-300 ${
              isActive ? "text-brand-dark" : "text-muted"
            }`}
          >
            {stage.label}
          </span>
        </div>
        <div className="mt-0.5 truncate text-[10px] leading-tight text-faint">
          {stage.detail}
        </div>
      </motion.div>

      {!isLast && (
        <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true" className="shrink-0">
          <path
            d="M0 5 H7 M4.5 2.5 L7 5 L4.5 7.5"
            fill="none"
            strokeWidth="1.25"
            strokeLinecap="round"
            strokeLinejoin="round"
            className={isActive ? "stroke-brand" : "stroke-line-strong"}
          />
        </svg>
      )}
    </div>
  );
}

function ReturnPath() {
  return (
    <svg width="46" height="10" viewBox="0 0 46 10" aria-hidden="true" className="shrink-0">
      <path
        d="M44 2 V6 Q44 8 42 8 H4 Q2 8 2 6 V4 M2 4 L0.5 6 M2 4 L3.5 6"
        fill="none"
        strokeWidth="1.1"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="stroke-line-strong"
      />
    </svg>
  );
}
