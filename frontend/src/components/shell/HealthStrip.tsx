/**
 * Operational truth in one line.
 *
 * Every figure here is a claim the system can be held to: sensors resolved out
 * of sensors requested, meters resolved, model latency, how many commands the
 * safety layer had to adjust, how many times the agent fell back. It quietly
 * demonstrates that nothing on this screen is staged, which is worth more than
 * any assertion in a slide.
 */

import type { ConnectionState, Status } from "../../api/types";
import { integer, number, type Severity } from "../../lib/format";
import { StatusDot } from "../ui/primitives";

export function HealthStrip({
  status,
  connection,
}: {
  status: Status | null;
  connection: ConnectionState;
}) {
  if (!status) {
    return (
      <div className="flex h-8 shrink-0 items-center gap-2 rounded-lg border border-line bg-surface px-3">
        <StatusDot severity="warn" pulse />
        <span className="text-[11px] text-faint">Starting simulation…</span>
      </div>
    );
  }

  const sensorsOk =
    status.variables_requested > 0 &&
    status.variables_resolved === status.variables_requested;
  const metersOk =
    status.meters_requested > 0 && status.meters_resolved === status.meters_requested;

  const items: { label: string; value: string; severity: Severity; title?: string }[] = [
    {
      label: "Simulation",
      value: status.simulation_running
        ? status.is_paused
          ? "paused"
          : "running"
        : "stopped",
      severity: status.simulation_running ? (status.is_paused ? "warn" : "ok") : "crit",
    },
    {
      label: "Sensors",
      value: `${status.variables_resolved}/${status.variables_requested}`,
      severity: sensorsOk ? "ok" : status.variables_requested === 0 ? "neutral" : "warn",
      title: "EnergyPlus output variables resolved to live handles",
    },
    {
      label: "Meters",
      value: `${status.meters_resolved}/${status.meters_requested}`,
      severity: metersOk ? "ok" : status.meters_requested === 0 ? "neutral" : "warn",
    },
    {
      label: "Agent",
      value: status.agent_running ? status.policy_name : "stopped",
      severity: status.agent_running ? "ok" : "crit",
    },
    {
      label: "Latency",
      value:
        status.llm_latency_seconds === null
          ? "n/a"
          : number(status.llm_latency_seconds, 1, "s"),
      severity: "neutral",
      title: "Mean model response time per decision",
    },
    {
      label: "Fallbacks",
      value: integer(status.policy_failures),
      severity: status.policy_failures === 0 ? "ok" : "warn",
      title: "Decisions where the deterministic policy had to take over",
    },
    {
      label: "Clamped",
      value: `${status.commands_adjusted}/${status.commands_submitted}`,
      severity: status.commands_adjusted > 0 ? "info" : "neutral",
      title: "Commands the safety layer adjusted before applying",
    },
    {
      label: "Stream",
      value: connection,
      severity: connection === "live" ? "ok" : connection === "offline" ? "crit" : "warn",
    },
  ];

  return (
    <div className="flex shrink-0 flex-wrap items-center gap-x-1 gap-y-1 rounded-lg border border-line bg-surface px-3 py-1.5">
      {items.map((item, index) => (
        <div key={item.label} className="flex items-center">
          <span className="flex items-center gap-1.5 px-1.5" title={item.title}>
            <StatusDot severity={item.severity} />
            <span className="text-[10px] uppercase tracking-[0.07em] text-faint">
              {item.label}
            </span>
            <span className="tabular text-[11px] font-semibold text-ink">{item.value}</span>
          </span>
          {index < items.length - 1 && (
            <span className="h-3 w-px bg-line" aria-hidden="true" />
          )}
        </div>
      ))}

      {status.error && (
        <span className="ml-auto truncate rounded border border-crit/30 bg-crit-tint px-2 py-0.5 text-[11px] font-medium text-crit">
          {status.error}
        </span>
      )}
    </div>
  );
}
