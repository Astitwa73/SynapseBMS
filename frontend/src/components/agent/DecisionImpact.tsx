/**
 * The centrepiece: one decision, end to end.
 *
 * Objective, observations, action, expected impact, policy agreement, safety
 * validation, applied action, measured outcome. Read top to bottom it answers
 * "why did the AI do that, was it checked, and did it work" without narration.
 *
 * Every figure carries where it came from. Expected impact is Derived and says
 * so; measured outcome is Measured and states the confound. The reasoning text
 * is the model's own words, never paraphrased or templated.
 */

import { AnimatePresence, motion } from "framer-motion";
import type { Decision } from "../../api/types";
import type { MeasuredOutcome } from "../../lib/outcome";
import {
  ACTION_GLYPHS,
  ACTION_LABELS,
  number,
  percent,
  signed,
} from "../../lib/format";
import { BASIS } from "../../lib/provenance";
import { ProvenanceTag } from "../ui/primitives";

const ACTION_TONE: Record<string, { border: string; text: string; bg: string }> = {
  raise_setpoint: { border: "border-ok/40", text: "text-ok", bg: "bg-ok-tint" },
  lower_setpoint: { border: "border-info/40", text: "text-info", bg: "bg-info-tint" },
  reduce_lighting: { border: "border-warn/40", text: "text-warn", bg: "bg-warn-tint" },
  hold: { border: "border-line-strong", text: "text-muted", bg: "bg-sunken" },
};

export function DecisionImpact({
  decision,
  previous,
  outcome,
  thinking,
}: {
  decision: Decision;
  previous: Decision | null;
  outcome: MeasuredOutcome | null;
  /** True while the policy is working on the *next* decision. The current
   * decision's reasoning stays visible throughout: it was produced and it is
   * still in force, so hiding it would show an absence that is not real. */
  thinking: boolean;
}) {
  const tone = ACTION_TONE[decision.action] ?? ACTION_TONE.hold;

  return (
    <div className="flex h-full min-h-0 flex-col gap-2 overflow-y-auto">
      <Section label="Current objective" basis={BASIS.objective}>
        <p className="text-sm font-semibold leading-snug text-ink">
          {decision.objective ?? "—"}
        </p>
      </Section>

      <Section label="Observed conditions" basis={BASIS.temperature}>
        <div className="flex flex-wrap gap-1">
          {decision.observations.map((observation, index) => (
            <motion.span
              key={observation}
              initial={{ opacity: 0, y: 3 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.05, duration: 0.2 }}
              className="tabular rounded border border-line bg-sunken px-1.5 py-0.5 text-[11px] text-muted"
            >
              {observation}
            </motion.span>
          ))}
        </div>
      </Section>

      <div className={`rounded border ${tone.border} ${tone.bg} p-2.5`}>
        <div className="flex items-center gap-2">
          <span className={`text-lg leading-none ${tone.text}`} aria-hidden="true">
            {ACTION_GLYPHS[decision.action]}
          </span>
          <span className={`text-sm font-bold uppercase tracking-wide ${tone.text}`}>
            {ACTION_LABELS[decision.action]}
          </span>
          <span className="tabular ml-auto text-[11px] text-muted">
            {decision.clock_label} · {decision.source}
          </span>
        </div>

        {/* Keyed on the decision, so a new one fades in over the old rather than
            the panel appearing to blank between cycles. */}
        <AnimatePresence mode="wait">
          <motion.p
            key={decision.sequence}
            initial={{ opacity: 0, y: 2 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
            className="mt-1.5 text-sm leading-snug text-ink"
          >
            {decision.reasoning}
          </motion.p>
        </AnimatePresence>

        {thinking && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="mt-2 flex items-center gap-1.5 border-t border-current/15 pt-1.5 text-[11px] text-muted"
          >
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand" />
            Reasoning about the next decision...
          </motion.div>
        )}
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        <ExpectedImpact decision={decision} />
        <MeasuredOutcomePanel decision={decision} outcome={outcome} />
      </div>

      <PolicyAgreement decision={decision} />

      {previous && (
        <div className="flex items-baseline gap-2 border-t border-line pt-2 text-[11px] text-faint">
          <span className="uppercase tracking-[0.06em]">Previous</span>
          <span aria-hidden="true">{ACTION_GLYPHS[previous.action]}</span>
          <span className="font-medium text-muted">{ACTION_LABELS[previous.action]}</span>
          <span className="tabular">{previous.clock_label}</span>
        </div>
      )}
    </div>
  );
}

function Section({
  label,
  basis,
  children,
}: {
  label: string;
  basis?: (typeof BASIS)[string];
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-0.5 flex items-center gap-1.5">
        <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-faint">
          {label}
        </span>
        {basis && <ProvenanceTag basis={basis} compact />}
      </div>
      {children}
    </div>
  );
}

function ExpectedImpact({ decision }: { decision: Decision }) {
  const impact = decision.impact;

  return (
    <div className="rounded border border-line bg-surface p-2.5">
      <div className="mb-1.5 flex items-center gap-1.5">
        <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-faint">
          Expected
        </span>
        <ProvenanceTag basis={BASIS.impact} />
      </div>

      {impact ? (
        <>
          <dl className="space-y-1">
            <Row
              label="Cooling"
              value={
                impact.cooling_change_pct === null
                  ? "no change"
                  : `${signed(impact.cooling_change_pct, 0)}%`
              }
            />
            <Row
              label="Power"
              value={
                impact.power_change_kw === null
                  ? "—"
                  : `${signed(impact.power_change_kw, 2)} kW`
              }
            />
            <Row
              label="Comfort"
              value={
                impact.comfort_change_pmv === null
                  ? "—"
                  : `${signed(impact.comfort_change_pmv)} PMV`
              }
            />
            <Row
              label="Carbon"
              value={
                impact.carbon_change_kg_per_hour === null
                  ? "—"
                  : `${signed(impact.carbon_change_kg_per_hour, 2)} kg/h`
              }
            />
          </dl>
          <p
            className="mt-1.5 cursor-help border-t border-line pt-1.5 text-[10px] leading-snug text-faint"
            title={impact.basis}
          >
            {impact.summary}
          </p>
        </>
      ) : (
        <p className="text-xs text-faint">No projection for this action.</p>
      )}
    </div>
  );
}

function MeasuredOutcomePanel({
  decision,
  outcome,
}: {
  decision: Decision;
  outcome: MeasuredOutcome | null;
}) {
  return (
    <div className="rounded border border-line bg-surface p-2.5">
      <div className="mb-1.5 flex items-center gap-1.5">
        <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-faint">
          Measured outcome
        </span>
        <ProvenanceTag basis={BASIS.outcome} />
      </div>

      {!outcome ? (
        <p className="text-xs text-faint">Waiting for the response window.</p>
      ) : (
        <>
          <dl className="space-y-1">
            <Row
              label="Cooling"
              value={
                outcome.coolingChangePct === null
                  ? "negligible load"
                  : `${signed(outcome.coolingChangePct, 0)}%`
              }
            />
            <Row
              label="Power"
              value={
                outcome.coolingBeforeKw === null || outcome.coolingAfterKw === null
                  ? "—"
                  : `${number(outcome.coolingBeforeKw, 2)} → ${number(outcome.coolingAfterKw, 2)} kW`
              }
            />
            <Row
              label="Comfort"
              value={outcome.pmvChange === null ? "—" : `${signed(outcome.pmvChange)} PMV`}
            />
          </dl>

          {!outcome.complete ? (
            <div className="mt-2">
              <div className="h-1 overflow-hidden rounded-full bg-sunken">
                <motion.div
                  className="h-full rounded-full bg-info"
                  animate={{ scaleX: outcome.progress }}
                  style={{ originX: 0 }}
                  transition={{ duration: 0.3 }}
                />
              </div>
              <p className="mt-1 text-[10px] text-faint">
                {percent(outcome.progress * 100)} through the response window
              </p>
            </div>
          ) : (
            <p
              className="mt-1.5 cursor-help border-t border-line pt-1.5 text-[10px] leading-snug text-faint"
              title={BASIS.outcome.detail}
            >
              Window complete. Weather and occupancy also changed across it, so this
              is what the building did, not what the decision alone caused.
            </p>
          )}
        </>
      )}
      <span className="sr-only">{decision.clock_label}</span>
    </div>
  );
}

/** Real agreement between two independent policies, in place of a self-reported
 * confidence score. Null means the deterministic policy is itself driving, which
 * is not disagreement and must not be rendered as such. */
function PolicyAgreement({ decision }: { decision: Decision }) {
  if (decision.used_fallback) {
    return (
      <Banner severity="warn" title="Deterministic fallback used">
        The language model did not return a usable decision, so the rule engine
        produced this one. The building never lost control.
      </Banner>
    );
  }

  if (decision.baseline_agrees === null) {
    return (
      <Banner severity="neutral" title="No baseline comparison">
        The rule engine is driving directly, so there is no second policy to
        compare against.
      </Banner>
    );
  }

  return decision.baseline_agrees ? (
    <Banner severity="ok" title="Rule baseline agrees">
      The deterministic policy independently chose{" "}
      {ACTION_LABELS[decision.baseline_action ?? "hold"].toLowerCase()} for the same
      building state.
    </Banner>
  ) : (
    <Banner severity="warn" title="Rule baseline differs">
      The deterministic policy would have chosen{" "}
      <strong>{ACTION_LABELS[decision.baseline_action ?? "hold"].toLowerCase()}</strong>.
      The model's choice was applied; the safety envelope constrains both equally.
    </Banner>
  );
}

function Banner({
  severity,
  title,
  children,
}: {
  severity: "ok" | "warn" | "neutral";
  title: string;
  children: React.ReactNode;
}) {
  const styles = {
    ok: "border-ok/30 bg-ok-tint",
    warn: "border-warn/30 bg-warn-tint",
    neutral: "border-line bg-sunken",
  };
  const dots = { ok: "bg-ok", warn: "bg-warn", neutral: "bg-line-strong" };

  return (
    <div className={`rounded border px-2.5 py-2 ${styles[severity]}`}>
      <div className="flex items-center gap-1.5">
        <span className={`h-1.5 w-1.5 rounded-full ${dots[severity]}`} />
        <span className="text-[11px] font-bold uppercase tracking-[0.06em] text-ink">
          {title}
        </span>
      </div>
      <p className="mt-0.5 text-[11px] leading-snug text-muted">{children}</p>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="text-[11px] text-faint">{label}</dt>
      <dd className="tabular text-xs font-semibold text-ink">{value}</dd>
    </div>
  );
}
