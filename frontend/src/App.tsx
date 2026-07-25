/**
 * Layout and wiring only.
 *
 * All live data enters through useBuildingStream and all choreography through
 * useDecisionCycle; this component distributes both and owns nothing else. Every
 * panel below is presentational and testable in isolation.
 */

import { useEffect, useState } from "react";
import { Header } from "./components/shell/Header";
import { HealthStrip } from "./components/shell/HealthStrip";
import { KpiRow } from "./components/shell/KpiRow";
import { SystemPipeline } from "./components/pipeline/SystemPipeline";
import { CycleCaption, CycleIndicator } from "./components/cycle/CycleIndicator";
import { AwaitingData, Card } from "./components/ui/primitives";
import {
  latestDecision,
  latestMetrics,
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
  const [architectureOpen, setArchitectureOpen] = useState(false);

  const cycle = useDecisionCycle({
    history: stream.history,
    decisions: stream.decisions,
    decisionEpoch: stream.decisionEpoch,
    cadence: config?.timesteps_per_decision ?? DEFAULT_CADENCE,
  });

  const metrics = latestMetrics(stream);
  const decision = latestDecision(stream);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "?") setArchitectureOpen((open) => !open);
      if (event.key === "Escape") setArchitectureOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="flex h-full flex-col gap-2 p-2">
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

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-2 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)_minmax(0,0.85fr)]">
        <Card title="Digital twin" subtitle={geometry ? `${geometry.floor_area_m2.toFixed(0)} m² · ${geometry.zones.length} zones` : undefined}>
          <AwaitingData label="Floor plan arrives in the next milestone" />
        </Card>

        <Card
          title="Decision impact"
          subtitle={<CycleCaption cycle={cycle} />}
          active={cycle.phase !== "idle" && cycle.phase !== "respond"}
        >
          {decision ? (
            <div className="space-y-2 text-sm">
              <div className="text-xs uppercase tracking-wide text-faint">
                {decision.objective}
              </div>
              <p className="text-ink">{decision.reasoning}</p>
              {decision.impact && (
                <p className="text-muted">{decision.impact.summary}</p>
              )}
            </div>
          ) : (
            <AwaitingData label="Awaiting the first agent decision" />
          )}
        </Card>

        <Card title="Live metrics">
          <AwaitingData label="Zone detail arrives in the next milestone" />
        </Card>
      </div>

      <Card title="System pipeline" className="shrink-0">
        <SystemPipeline phase={cycle.phase} />
      </Card>

      <HealthStrip status={stream.status} connection={stream.connection} />

      {architectureOpen && (
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-ink/40 p-6"
          onClick={() => setArchitectureOpen(false)}
        >
          <div
            className="max-w-lg rounded-lg border border-line bg-surface p-6"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 className="text-sm font-bold text-ink">System architecture</h2>
            <p className="mt-2 text-xs text-muted">
              Full overlay arrives in a later milestone. Press Escape to close.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
