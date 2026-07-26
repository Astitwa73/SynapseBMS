/**
 * Playback control for presenting.
 *
 * Drives the real simulation thread -- pause holds EnergyPlus inside its own
 * callback, step releases exactly one decision's worth of timesteps. No data is
 * faked or replayed; the building simply stops advancing while you talk.
 */

import { useEffect, useState } from "react";
import { api } from "../../api/client";

type Busy = "pause" | "resume" | "step" | null;

export function DemoControls({ paused, running }: { paused: boolean; running: boolean }) {
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (action: Busy, call: () => Promise<unknown>) => {
    setBusy(action);
    setError(null);
    try {
      await call();
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Request failed");
    } finally {
      setBusy(null);
    }
  };

  const toggle = () =>
    paused ? run("resume", api.resume) : run("pause", api.pause);
  const step = () => run("step", api.step);

  // Space toggles, right arrow steps. Both are muscle memory from media players
  // and let a presenter drive without looking away from the screen.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;

      if (event.code === "Space") {
        event.preventDefault();
        toggle();
      }
      if (event.code === "ArrowRight") {
        event.preventDefault();
        step();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [paused]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!running) return null;

  return (
    <div className="flex shrink-0 items-center gap-1" title={error ?? undefined}>
      <button
        type="button"
        onClick={toggle}
        disabled={busy !== null}
        title={paused ? "Resume (Space)" : "Pause (Space)"}
        className={`flex items-center gap-1.5 rounded border px-2 py-1 text-[11px] font-semibold transition-colors disabled:opacity-50 ${
          paused
            ? "border-ok/40 bg-ok-tint text-ok hover:bg-ok/10"
            : "border-line bg-surface text-muted hover:border-line-strong hover:text-ink"
        }`}
      >
        <Glyph paused={paused} />
        {paused ? "Resume" : "Pause"}
      </button>

      <button
        type="button"
        onClick={step}
        disabled={busy !== null}
        title="Advance one decision (Right arrow)"
        className="flex items-center gap-1.5 rounded border border-line bg-surface px-2 py-1 text-[11px] font-semibold text-muted transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50"
      >
        <svg width="9" height="9" viewBox="0 0 9 9" aria-hidden="true">
          <path d="M1 1 L6 4.5 L1 8 Z" className="fill-current" />
          <rect x="7" y="1" width="1.4" height="7" className="fill-current" />
        </svg>
        Step
      </button>

      {error && (
        <span className="max-w-40 truncate text-[10px] text-crit" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

function Glyph({ paused }: { paused: boolean }) {
  return (
    <svg width="9" height="9" viewBox="0 0 9 9" aria-hidden="true">
      {paused ? (
        <path d="M1.5 1 L8 4.5 L1.5 8 Z" className="fill-current" />
      ) : (
        <>
          <rect x="1.5" y="1" width="2.2" height="7" className="fill-current" />
          <rect x="5.3" y="1" width="2.2" height="7" className="fill-current" />
        </>
      )}
    </svg>
  );
}
