/**
 * Data that does not change during a run: geometry and configuration.
 *
 * Fetched once and retried on failure, because the backend serves geometry only
 * after the building has started and the dashboard may connect first.
 */

import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Config, Geometry } from "../api/types";

const RETRY_MS = 2000;

export function useStaticData() {
  const [geometry, setGeometry] = useState<Geometry | null>(null);
  const [config, setConfig] = useState<Config | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    const load = async () => {
      try {
        const [nextGeometry, nextConfig] = await Promise.all([api.geometry(), api.config()]);
        if (cancelled) return;
        setGeometry(nextGeometry);
        setConfig(nextConfig);
      } catch {
        if (!cancelled) timer = window.setTimeout(load, RETRY_MS);
      }
    };

    load();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, []);

  return { geometry, config };
}
