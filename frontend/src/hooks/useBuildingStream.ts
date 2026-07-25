/**
 * The single source of live data.
 *
 * Owns the WebSocket, the reducer and reconnection. Every component below this
 * is presentational and takes props, so there is exactly one place where data
 * arrives and one place where it is shaped.
 *
 * Reconnection relies on the server's sequence cursor rather than client state:
 * on reconnect the server replays a snapshot, and updates carry only unseen
 * sequences. A dropped connection therefore produces neither a gap nor a
 * duplicate in the history, and no session state is held server-side.
 */

import { useCallback, useEffect, useReducer, useRef } from "react";
import type {
  ConnectionState,
  Decision,
  Metrics,
  Status,
  StreamMessage,
} from "../api/types";

/** ~40 minutes of simulated time at 15-minute timesteps: enough for every chart
 * on screen, bounded so a long run cannot grow without limit. */
const HISTORY_LIMIT = 480;
const DECISION_LIMIT = 60;

const RECONNECT_DELAYS_MS = [500, 1000, 2000, 4000, 8000];

export interface BuildingState {
  connection: ConnectionState;
  status: Status | null;
  history: Metrics[];
  decisions: Decision[];
  /** Bumped whenever a decision arrives, so the cycle orchestrator can react to
   * "a new decision exists" without diffing decision arrays. */
  decisionEpoch: number;
  lastMessageAt: number | null;
}

type Action =
  | { type: "connection"; state: ConnectionState }
  | { type: "message"; message: StreamMessage; at: number };

const initialState: BuildingState = {
  connection: "connecting",
  status: null,
  history: [],
  decisions: [],
  decisionEpoch: 0,
  lastMessageAt: null,
};

function appendBounded<T>(existing: T[], incoming: T[], limit: number): T[] {
  if (incoming.length === 0) return existing;
  const combined = existing.concat(incoming);
  return combined.length > limit ? combined.slice(combined.length - limit) : combined;
}

function reducer(state: BuildingState, action: Action): BuildingState {
  switch (action.type) {
    case "connection":
      return { ...state, connection: action.state };

    case "message": {
      const { message, at } = action;

      if (message.type === "snapshot") {
        return {
          ...state,
          connection: "live",
          status: message.status,
          history: message.history.slice(-HISTORY_LIMIT),
          decisions: message.decisions.slice(-DECISION_LIMIT),
          decisionEpoch: state.decisionEpoch + 1,
          lastMessageAt: at,
        };
      }

      return {
        ...state,
        connection: "live",
        status: message.status,
        history: appendBounded(state.history, message.metrics, HISTORY_LIMIT),
        decisions: appendBounded(state.decisions, message.decisions, DECISION_LIMIT),
        decisionEpoch:
          message.decisions.length > 0 ? state.decisionEpoch + 1 : state.decisionEpoch,
        lastMessageAt: at,
      };
    }
  }
}

export function useBuildingStream(): BuildingState {
  const [state, dispatch] = useReducer(reducer, initialState);
  const socketRef = useRef<WebSocket | null>(null);
  const attemptRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const closedByUs = useRef(false);

  const connect = useCallback(() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${protocol}//${window.location.host}/ws`);
    socketRef.current = socket;

    socket.onopen = () => {
      attemptRef.current = 0;
      dispatch({ type: "connection", state: "live" });
    };

    socket.onmessage = (event) => {
      try {
        dispatch({
          type: "message",
          message: JSON.parse(event.data) as StreamMessage,
          at: Date.now(),
        });
      } catch {
        // A malformed frame is not worth tearing down a working connection for.
      }
    };

    socket.onclose = () => {
      if (closedByUs.current) return;

      const attempt = attemptRef.current;
      dispatch({ type: "connection", state: attempt === 0 ? "reconnecting" : "offline" });

      const delay = RECONNECT_DELAYS_MS[Math.min(attempt, RECONNECT_DELAYS_MS.length - 1)];
      attemptRef.current = attempt + 1;
      timerRef.current = window.setTimeout(connect, delay);
    };

    socket.onerror = () => socket.close();
  }, []);

  useEffect(() => {
    closedByUs.current = false;
    connect();

    return () => {
      closedByUs.current = true;
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
      socketRef.current?.close();
    };
  }, [connect]);

  return state;
}

export function latestMetrics(state: BuildingState): Metrics | null {
  return state.history.length > 0 ? state.history[state.history.length - 1] : null;
}

export function latestDecision(state: BuildingState): Decision | null {
  return state.decisions.length > 0 ? state.decisions[state.decisions.length - 1] : null;
}

export function previousDecision(state: BuildingState): Decision | null {
  return state.decisions.length > 1 ? state.decisions[state.decisions.length - 2] : null;
}
