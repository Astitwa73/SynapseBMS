/**
 * The audit trail: every decision the agent has taken, newest first.
 *
 * Shows the chain rather than the snapshot -- what was chosen, whether the
 * deterministic baseline agreed, and whether the safety layer intervened. This
 * is the record an operator would be asked for after an incident, which is why
 * it carries provenance rather than being a pretty activity feed.
 */

import { AnimatePresence, motion } from "framer-motion";
import type { Decision } from "../../api/types";
import { ACTION_GLYPHS, ACTION_LABELS, number } from "../../lib/format";

const TONE: Record<string, string> = {
  raise_setpoint: "text-ok",
  lower_setpoint: "text-info",
  reduce_lighting: "text-warn",
  hold: "text-muted",
};

export function DecisionTimeline({ decisions }: { decisions: Decision[] }) {
  const recent = [...decisions].reverse().slice(0, 40);

  if (recent.length === 0) {
    return <p className="text-xs text-faint">No decisions yet.</p>;
  }

  return (
    <ol className="flex h-full flex-col gap-0.5 overflow-y-auto pr-1">
      <AnimatePresence initial={false}>
        {recent.map((decision, index) => (
          <motion.li
            key={`${decision.sequence}-${decision.decided_at}`}
            initial={index === 0 ? { opacity: 0, y: -6 } : false}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25 }}
            className="flex items-baseline gap-1.5 border-b border-line/50 py-1 last:border-0"
          >
            <span className="tabular w-20 shrink-0 text-[10px] text-faint">
              {decision.clock_label}
            </span>
            <span className={`shrink-0 text-[11px] ${TONE[decision.action]}`} aria-hidden="true">
              {ACTION_GLYPHS[decision.action]}
            </span>
            <span
              className={`shrink-0 text-[11px] font-semibold ${TONE[decision.action]}`}
            >
              {ACTION_LABELS[decision.action]}
            </span>
            {decision.cooling_setpoint_c !== null && (
              <span className="tabular shrink-0 text-[10px] text-muted">
                {number(decision.cooling_setpoint_c, 1, "°C")}
              </span>
            )}

            <span className="ml-auto flex shrink-0 items-center gap-1">
              {decision.used_fallback && <Chip tone="warn" title="Model failed; rule engine took over">fallback</Chip>}
              {decision.baseline_agrees === false && !decision.used_fallback && (
                <Chip tone="info" title={`Baseline would have chosen ${ACTION_LABELS[decision.baseline_action ?? "hold"]}`}>
                  differs
                </Chip>
              )}
              {decision.safety_adjustments.length > 0 && (
                <Chip tone="warn" title={decision.safety_adjustments.join("\n")}>
                  clamped
                </Chip>
              )}
            </span>
          </motion.li>
        ))}
      </AnimatePresence>
    </ol>
  );
}

function Chip({
  children,
  tone,
  title,
}: {
  children: React.ReactNode;
  tone: "warn" | "info";
  title?: string;
}) {
  const styles =
    tone === "warn"
      ? "border-warn/30 bg-warn-tint text-warn"
      : "border-info/30 bg-info-tint text-info";
  return (
    <span
      title={title}
      className={`cursor-help rounded border px-1 py-px text-[9px] font-semibold uppercase ${styles}`}
    >
      {children}
    </span>
  );
}
