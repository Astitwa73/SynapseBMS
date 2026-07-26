/**
 * Identity, simulated clock, and connection truth.
 *
 * The connection pill is deliberately prominent. A dashboard that silently
 * freezes when its socket drops is indistinguishable from a building that has
 * stopped changing, and confusing the two on stage is unrecoverable.
 */

import { motion } from "framer-motion";
import type { ConnectionState, Metrics, Status } from "../../api/types";
import { CycleIndicator } from "../cycle/CycleIndicator";
import type { DecisionCycle } from "../../hooks/useDecisionCycle";
import { clockLabel, number } from "../../lib/format";
import { StatusDot } from "../ui/primitives";
import { DemoControls } from "./DemoControls";

const CONNECTION_COPY: Record<ConnectionState, { label: string; severity: "ok" | "warn" | "crit" }> =
  {
    connecting: { label: "Connecting", severity: "warn" },
    live: { label: "Live", severity: "ok" },
    reconnecting: { label: "Reconnecting", severity: "warn" },
    offline: { label: "Offline", severity: "crit" },
  };

export function Header({
  metrics,
  status,
  connection,
  cycle,
  modelName,
  onOpenArchitecture,
}: {
  metrics: Metrics | null;
  status: Status | null;
  connection: ConnectionState;
  cycle: DecisionCycle;
  modelName: string | null;
  onOpenArchitecture: () => void;
}) {
  const connectionState = CONNECTION_COPY[connection];
  const paused = status?.is_paused ?? false;

  return (
    <header className="flex shrink-0 items-center gap-4 border-b border-line bg-surface px-3 py-1.5">
      <div className="flex shrink-0 items-center gap-2.5">
        <span className="h-6 w-1 rounded-sm bg-brand" aria-hidden="true" />
        <div>
          <h1 className="text-[13px] font-bold leading-tight tracking-tight text-ink">
            Autonomous Building Management
          </h1>
          <p className="text-[11px] leading-tight text-faint">
            {modelName ?? "—"} · supervisory AI control
          </p>
        </div>
      </div>

      <div className="hidden shrink-0 items-baseline gap-2 border-l border-line pl-4 lg:flex">
        <span className="tabular text-lg font-semibold leading-none text-ink">
          {metrics ? clockLabel(metrics.clock.label) : "—"}
        </span>
        <span className="text-[11px] text-faint">simulated</span>
        {paused && (
          <motion.span
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="rounded border border-warn/30 bg-warn-tint px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-warn"
          >
            Paused
          </motion.span>
        )}
      </div>

      <div className="mx-auto hidden xl:block">
        <CycleIndicator cycle={cycle} />
      </div>

      <div className="ml-auto flex shrink-0 items-center gap-3">
        <DemoControls
          paused={paused}
          running={status?.simulation_running ?? false}
        />

        <PolicyBadge status={status} />

        <span className="flex items-center gap-1.5 rounded border border-line bg-sunken px-2 py-1">
          <StatusDot
            severity={connectionState.severity}
            pulse={connection === "reconnecting" || connection === "connecting"}
          />
          <span className="text-[11px] font-medium text-muted">{connectionState.label}</span>
        </span>

        <button
          type="button"
          onClick={onOpenArchitecture}
          className="rounded border border-line px-2 py-1 text-[11px] font-medium text-muted transition-colors hover:border-line-strong hover:text-ink"
          title="System architecture (press ?)"
        >
          Architecture
        </button>
      </div>
    </header>
  );
}

function PolicyBadge({ status }: { status: Status | null }) {
  if (!status) return null;

  const isLlm = status.policy_name !== "rule-based";
  const latency = status.llm_latency_seconds;

  return (
    <span className="hidden items-center gap-2 rounded border border-line bg-sunken px-2 py-1 md:flex">
      <span className="text-[10px] uppercase tracking-[0.07em] text-faint">Policy</span>
      <span className="text-[11px] font-semibold text-ink">{status.policy_name}</span>
      {isLlm && latency !== null && (
        <span className="tabular text-[11px] text-muted">{number(latency, 1, "s")}</span>
      )}
    </span>
  );
}
