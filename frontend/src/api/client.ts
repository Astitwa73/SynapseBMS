/**
 * REST calls.
 *
 * Same-origin everywhere: Vite proxies /api to the backend in development, and
 * FastAPI serves the built bundle in production. That removes environment-
 * specific base URLs from the client entirely, which is one fewer thing that can
 * be wrong on demo day.
 */

import type { AppliedCommand, Config, Geometry, Report, Status } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  if (!response.ok) {
    const detail = await response
      .json()
      .then((body) => body.detail as string)
      .catch(() => response.statusText);
    throw new Error(detail || `Request failed: ${response.status}`);
  }

  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export const api = {
  geometry: () => request<Geometry>("/api/geometry"),
  config: () => request<Config>("/api/config"),
  status: () => request<Status>("/api/status"),
  report: () => request<Report>("/api/report"),

  /** Manual override. Passes through the same safety envelope as the agent, so
   * the response reports what was applied rather than what was asked for. */
  setSetpoint: (celsius: number, source = "operator") =>
    request<AppliedCommand>("/api/control/setpoint", {
      method: "POST",
      body: JSON.stringify({ cooling_setpoint_c: celsius, source }),
    }),

  releaseControl: () => request<void>("/api/control/release", { method: "POST" }),

  pause: () => request<Status>("/api/simulation/pause", { method: "POST" }),
  resume: () => request<Status>("/api/simulation/resume", { method: "POST" }),
  step: () => request<Status>("/api/simulation/step", { method: "POST" }),
};
