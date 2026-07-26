/**
 * Layout and wiring only.
 *
 * All live data enters through useBuildingStream and all choreography through
 * useDecisionCycle; this component distributes both and owns nothing else. Every
 * panel below is presentational and testable in isolation.
 */

import { useEffect, useMemo, useState } from "react";
import { Header } from "./components/shell/Header";
import { HealthStrip } from "./components/shell/HealthStrip";
import { KpiRow } from "./components/shell/KpiRow";
import { SystemPipeline } from "./components/pipeline/SystemPipeline";
import { CycleCaption, CycleIndicator } from "./components/cycle/CycleIndicator";
import { AwaitingData, Card } from "./components/ui/primitives";
import { DecisionImpact } from "./components/agent/DecisionImpact";
import { SafetyLayer, fromDecision } from "./components/agent/SafetyLayer";
import { measureOutcome } from "./lib/outcome";
import { BenchmarkCard, useBenchmark } from "./components/metrics/BenchmarkCard";
import { FloorPlan } from "./components/twin/FloorPlan";
import { DecisionTimeline } from "./components/agent/DecisionTimeline";
import {
  METRIC_KEYS,
  METRIC_LABELS,
  TrendChart,
  type MetricKey,
} from "./components/metrics/TrendChart";
import { ArchitectureOverlay } from "./components/shell/ArchitectureOverlay";
import {
  latestDecision,
  latestMetrics,
  previousDecision,
  useBuildingStream,
} from "./hooks/useBuildingStream";
import { useDecisionCycle } from "./hooks/useDecisionCycle";
import { useStaticData } from "./hooks/useStaticData";
import { estimatedSavingPct, useReport } from "./hooks/useReport";

const DEFAULT_CADENCE = 12;

export default function App() {
  const stream = useBuildingStream();
  const { geometry, config } = useStaticData();
  const report = useReport();
  const benchmark = useBenchmark();
  const [architectureOpen, setArchitectureOpen] = useState(false);
  const [metric, setMetric] = useState<MetricKey>("power");

  const cycle = useDecisionCycle({
    history: stream.history,
    decisions: stream.decisions,
    decisionEpoch: stream.decisionEpoch,
    cadence: config?.timesteps_per_decision ?? DEFAULT_CADENCE,
  });

  const metrics = latestMetrics(stream);
  const decision = latestDecision(stream);
  const previous = previousDecision(stream);
  const cadence = config?.timesteps_per_decision ?? DEFAULT_CADENCE;

  const outcome = useMemo(
    () => measureOutcome(decision, stream.history, cadence),
    [decision, stream.history, cadence],
  );

  // An operator or MCP command replaces what the safety panel shows until the
  // next agent decision, because that command is what most recently traversed
  // the clamp.
  const [injected, setInjected] = useState<ReturnType<typeof fromDecision>>(null);
  useEffect(() => setInjected(null), [decision?.sequence]);
  const passage = injected ?? fromDecision(decision);

  // The agent names a zone in its reasoning; outlining that zone on the plan is
  // what connects the sentence to a place in the building.
  const highlightedZone = useMemo(() => {
    if (!decision || !geometry) return null;
    return (
      geometry.zones.find((zone) => decision.reasoning.includes(zone.name))?.name ?? null
    );
  }, [decision, geometry]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "?") setArchitectureOpen((open) => !open);
      if (event.key === "Escape") setArchitectureOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    // Viewport-locked on a real screen: panels scroll internally, the page does
    // not. On a small window that would crush every row to a sliver, so below lg
    // the page scrolls instead -- a scrollbar beats unreadable content.
    <div className="flex min-h-screen flex-col gap-1.5 p-1.5 lg:h-screen lg:overflow-hidden">
      <Header
        metrics={metrics}
        status={stream.status}
        connection={stream.connection}
        cycle={cycle}
        modelName={config?.model_name ?? null}
        onOpenArchitecture={() => setArchitectureOpen(true)}
      />

      {/* Shown below xl, where the header cannot hold the indicator. The loop is
          the focal point of the interface and must never be off-screen. */}
      <div className="flex items-center justify-between gap-3 rounded-lg border border-line bg-surface px-3 py-2 xl:hidden">
        <CycleIndicator cycle={cycle} />
      </div>

      <KpiRow
        metrics={metrics}
        history={stream.history}
        status={stream.status}
        carbonBasis={geometry?.carbon_basis ?? null}
        estimatedSavingPct={estimatedSavingPct(report)}
      />

      <div className="grid min-h-[26rem] flex-1 grid-cols-1 gap-1.5 lg:min-h-0 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_minmax(0,0.9fr)]">
          <Card
            title="Digital twin"
            subtitle={
              geometry
                ? `${geometry.floor_area_m2.toFixed(0)} m² · ${geometry.zones.length} zones`
                : undefined
            }
            className="min-h-0"
          >
            <FloorPlan
              geometry={geometry}
              metrics={metrics}
              highlightZone={highlightedZone}
            />
          </Card>

        <Card
          title="Decision impact"
          subtitle={<CycleCaption cycle={cycle} />}
          active={cycle.phase !== "idle" && cycle.phase !== "respond"}
          className="min-h-0"
        >
          {decision ? (
            <DecisionImpact
              decision={decision}
              previous={previous}
              outcome={outcome}
              thinking={cycle.isThinking}
            />
          ) : (
            <AwaitingData label="Awaiting the first agent decision" />
          )}
        </Card>

        <div className="flex min-h-0 flex-col gap-1.5">
          <Card
            title="Safety layer"
            active={cycle.phase === "validate"}
            className="min-h-0 flex-1"
          >
            <SafetyLayer
              passage={passage}
              limits={config?.limits ?? null}
              active={cycle.phase === "validate"}
              onInject={setInjected}
            />
          </Card>

          <Card
            title="Decision audit trail"
            subtitle={`${stream.decisions.length} recorded`}
            className="h-44 shrink-0"
          >
            <DecisionTimeline decisions={stream.decisions} />
          </Card>
        </div>
      </div>

      {/* A wide table and a wide pipeline both suit a full-width strip; stacking
          the benchmark above the floor plan squeezed both into unreadable boxes. */}
      <div className="grid shrink-0 grid-cols-1 gap-1.5 lg:max-h-48 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.1fr)]">
        <Card title="System pipeline" className="min-h-0">
          <SystemPipeline phase={cycle.phase} />
        </Card>

        <Card
          title="Trends"
          subtitle="Vertical rules mark decisions"
          className="min-h-0"
          action={
            <div className="flex shrink-0 gap-1">
              {METRIC_KEYS.map((key) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setMetric(key)}
                  className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold transition-colors ${
                    metric === key
                      ? "border-brand bg-brand text-white"
                      : "border-line bg-surface text-muted hover:text-ink"
                  }`}
                >
                  {METRIC_LABELS[key]}
                </button>
              ))}
            </div>
          }
        >
          <TrendChart
            history={stream.history}
            decisions={stream.decisions}
            metric={metric}
          />
        </Card>

        <Card
          title="Validated performance"
          subtitle="Measured on identical conditions, not estimated"
          className="min-h-0"
        >
          <BenchmarkCard benchmark={benchmark} />
        </Card>
      </div>

      <HealthStrip status={stream.status} connection={stream.connection} />

      {/* Rendered conditionally rather than through AnimatePresence: the exit
          animation did not resolve in this environment and left the overlay
          mounted after close. A modal that cannot be dismissed is worse than one
          without a fade. */}
      {architectureOpen && (
        <ArchitectureOverlay onClose={() => setArchitectureOpen(false)} />
      )}

    </div>
  );
}
