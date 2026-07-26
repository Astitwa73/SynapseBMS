/**
 * The safety envelope, as an event rather than a claim.
 *
 * Requested -> validated -> applied, driven by whatever command last passed
 * through ControlStore. Deliberately the same component for every origin: an
 * agent decision, an operator override and an MCP client all render here,
 * because they all traverse the same clamping code. Showing one path would
 * imply the others bypass it.
 *
 * The pass-through case animates too. If the gate only appeared on intervention,
 * a viewer would conclude it is an exception handler rather than something every
 * command goes through.
 */

import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import { api } from "../../api/client";
import type { AppliedCommand, Decision, SafetyLimits } from "../../api/types";
import { number } from "../../lib/format";

interface Passage {
  requested: number | null;
  applied: number | null;
  adjustments: string[];
  origin: string;
  at: number;
}

export function fromDecision(decision: Decision | null): Passage | null {
  if (!decision) return null;
  return {
    requested: decision.requested_setpoint_c,
    applied: decision.cooling_setpoint_c,
    adjustments: decision.safety_adjustments,
    origin: decision.source,
    at: decision.sequence,
  };
}

export function fromCommand(command: AppliedCommand, origin: string, requested: number): Passage {
  return {
    requested,
    applied: command.cooling_setpoint_c,
    adjustments: command.safety_adjustments,
    origin,
    at: Date.now(),
  };
}

export function SafetyLayer({
  passage,
  limits,
  active,
  onInject,
}: {
  passage: Passage | null;
  limits: SafetyLimits | null;
  active: boolean;
  onInject: (passage: Passage) => void;
}) {
  const clamped = (passage?.adjustments.length ?? 0) > 0;

  return (
    <div className="flex h-full flex-col gap-2 overflow-y-auto">
      {passage ? (
        <>
          <div className="flex items-stretch gap-1.5">
            <Node label="Requested" value={number(passage.requested, 1, "°C")} tone="neutral" />
            <Connector active={active} clamped={clamped} />
            <Node
              label="Validated"
              value={clamped ? "adjusted" : "within limits"}
              tone={clamped ? "warn" : "ok"}
              pulse={active}
            />
            <Connector active={active} clamped={clamped} />
            <Node label="Applied" value={number(passage.applied, 1, "°C")} tone="ok" />
          </div>

          <AnimatePresence mode="popLayout">
            {passage.adjustments.map((adjustment) => (
              <motion.div
                key={adjustment}
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.25 }}
                className="overflow-hidden"
              >
                <p className="rounded border border-warn/30 bg-warn-tint px-2 py-1 text-[11px] font-medium text-warn">
                  {adjustment}
                </p>
              </motion.div>
            ))}
          </AnimatePresence>

          {!clamped && (
            <p className="text-[11px] text-faint">
              Passed unchanged. Every command is checked, whether or not it is adjusted.
            </p>
          )}

          <p className="text-[11px] text-faint">
            Origin: <span className="font-medium text-muted">{passage.origin}</span>
          </p>
        </>
      ) : (
        <p className="text-xs text-faint">No command has passed through yet.</p>
      )}

      {limits && <LimitsSummary limits={limits} />}
      <InjectControl onInject={onInject} />
    </div>
  );
}

function Node({
  label,
  value,
  tone,
  pulse = false,
}: {
  label: string;
  value: string;
  tone: "neutral" | "ok" | "warn";
  pulse?: boolean;
}) {
  const styles = {
    neutral: "border-line bg-sunken text-ink",
    ok: "border-ok/40 bg-ok-tint text-ok",
    warn: "border-warn/40 bg-warn-tint text-warn",
  };

  return (
    <motion.div
      animate={pulse ? { scale: [1, 1.02, 1] } : { scale: 1 }}
      transition={{ duration: 0.6 }}
      className={`flex-1 rounded border px-2 py-1.5 text-center ${styles[tone]}`}
    >
      <div className="text-[9px] font-semibold uppercase tracking-[0.08em] opacity-70">
        {label}
      </div>
      <div className="tabular mt-0.5 text-sm font-bold">{value}</div>
    </motion.div>
  );
}

function Connector({ active, clamped }: { active: boolean; clamped: boolean }) {
  return (
    <svg width="16" height="40" viewBox="0 0 16 40" className="shrink-0 self-center">
      <line
        x1="0"
        y1="20"
        x2="12"
        y2="20"
        strokeWidth="1.5"
        strokeLinecap="round"
        className={`${clamped ? "stroke-warn" : "stroke-line-strong"} ${active ? "animate-flow" : ""}`}
      />
      <path
        d="M9 17 L12 20 L9 23"
        fill="none"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        className={clamped ? "stroke-warn" : "stroke-line-strong"}
      />
    </svg>
  );
}

function LimitsSummary({ limits }: { limits: SafetyLimits }) {
  const rules = [
    `Cooling ${limits.min_cooling_setpoint_c}–${limits.max_cooling_setpoint_c} °C`,
    `Heating ≤ cooling − ${limits.min_deadband_c} °C`,
    `Max ${limits.max_setpoint_change_c} °C per step`,
    `Lighting ≥ ${(limits.min_lighting_fraction * 100).toFixed(0)}%`,
  ];

  return (
    <div className="mt-auto border-t border-line pt-2">
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-faint">
        Enforced limits
      </div>
      <ul className="grid grid-cols-2 gap-x-2 gap-y-0.5">
        {rules.map((rule) => (
          <li key={rule} className="tabular text-[11px] text-muted">
            {rule}
          </li>
        ))}
      </ul>
      <p className="mt-1 text-[10px] leading-snug text-faint">
        An inverted deadband terminates EnergyPlus outright, so that rule is
        enforced last and unconditionally.
      </p>
    </div>
  );
}

/** Lets a viewer cause the intervention themselves. The request is genuine: it
 * goes through the real endpoint and the real clamp, and the response shown is
 * what the backend actually applied. */
function InjectControl({ onInject }: { onInject: (passage: Passage) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const inject = async (celsius: number) => {
    setBusy(true);
    setError(null);
    try {
      const applied = await api.setSetpoint(celsius, "demo-unsafe");
      onInject(fromCommand(applied, "demo-unsafe", celsius));
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Request failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded border border-line bg-sunken p-2">
      <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-faint">
        Try it — send an unsafe command
      </div>
      <div className="flex gap-1.5">
        <button
          type="button"
          disabled={busy}
          onClick={() => inject(4)}
          className="flex-1 rounded border border-crit/40 bg-crit-tint px-2 py-1 text-[11px] font-semibold text-crit transition-colors hover:bg-crit/10 disabled:opacity-50"
        >
          Request 4 °C
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => inject(45)}
          className="flex-1 rounded border border-crit/40 bg-crit-tint px-2 py-1 text-[11px] font-semibold text-crit transition-colors hover:bg-crit/10 disabled:opacity-50"
        >
          Request 45 °C
        </button>
      </div>
      {error && <p className="mt-1 text-[11px] text-crit">{error}</p>}
      <p className="mt-1 text-[10px] leading-snug text-faint">
        A real request to the same endpoint the agent uses. The value shown above
        is what the backend applied.
      </p>
    </div>
  );
}
