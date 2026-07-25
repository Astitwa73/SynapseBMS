/**
 * The period report, polled.
 *
 * Not on the WebSocket because it is a summary over the whole run rather than a
 * per-timestep value: pushing it 4 times a second would recompute it 4 times a
 * second to show a number that moves slowly.
 */

import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Report } from "../api/types";

const POLL_MS = 15000;

export function useReport(): Report | null {
  const [report, setReport] = useState<Report | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const next = await api.report();
        if (!cancelled) setReport(next);
      } catch {
        // The report is unavailable until the first samples land; the next poll
        // will pick it up rather than surfacing a transient failure.
      }
    };

    load();
    const timer = window.setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  return report;
}

export function estimatedSavingPct(report: Report | null): number | null {
  const value = report?.savings?.estimated_cooling_saving_pct;
  return typeof value === "number" ? value : null;
}
