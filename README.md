# Autonomous Building Management System

An AI agent that reads live sensor data from an EnergyPlus building simulation,
reasons about building state, and writes control decisions back into the running
simulation — closing the loop the way a supervisory BMS layer does.

## Architecture

```
EnergyPlus ──► Sensor Collector ──► State Store ──► MCP Server ──► LLM Agent
(own thread)                            ▲                              │
     ▲                                  │                              ▼
     └──── Control Layer ◄── Control State ◄──────────── Decision Engine
                                        │
                              FastAPI ──┴──► WebSocket ──► React Dashboard
```

The simulation advances in milliseconds; the agent reasons in seconds. They are
decoupled through an immutable state snapshot, so the simulation applies the last
known-good command every timestep and keeps running safely even if the agent
stalls or fails. Every command is clamped to a comfort/safety band by the
Decision Engine before it reaches an actuator.

## Prerequisites

**EnergyPlus** — install from the
[releases page](https://github.com/NatLabRockies/EnergyPlus/releases) using the
`Windows-x86_64.exe` installer and the default install path. `pyenergyplus` ships
inside that install rather than on PyPI, which is why it is absent from
`requirements.txt`; `backend/config/paths.py` locates it at runtime.

A non-default install location is supported via the `ENERGYPLUS_DIR` environment
variable.

**Python 3.10+, 64-bit.** The API is loaded through ctypes, so the Python version
does not need to match EnergyPlus, but the architecture does.

**Ollama** with Llama 3 — required from the agent module onward.

## Setup

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt -r requirements-dev.txt
```

## Verify the environment

Run these in order. Each one gates the next.

```bash
python scripts/verify_energyplus.py --run   # can we get in-run callbacks?
python scripts/prepare_model.py             # copy the building model into models/
python scripts/inspect_model.py             # which sensors does the model expose?
```

`verify_energyplus.py` must report a non-zero callback count — that is the proof
that closed-loop control is possible at all. `inspect_model.py` writes
`docs/available_sensors.json`, which is the contract the sensor layer is built
against.

## Run the simulation

```bash
python scripts/run_simulation.py --speed 0.12 --seconds 45
```

Live sensor data should stream with contiguous sequence numbers, occupancy
rising to 52 at 08:00 and whole-building power following it.

### Why an annual run period, not design days

Design days are *sizing* scenarios: their schedules deliberately zero out
occupancy so equipment is sized for the worst case. That produces an empty
building with flat energy use — nothing for an agent to reason about. The annual
run period carries real weather and real occupancy schedules instead.

An unthrottled annual run reaches December in about 11 seconds, so the engine
fast-forwards at full speed to a chosen date (`--from-date`) and only then drops
to demo pace.

### Derived metrics

Two dashboard metrics are computed rather than read, because this model does not
produce them:

| Metric | Source |
| --- | --- |
| CO₂ / air quality | Steady-state mass balance from occupant count and mechanical ventilation mass flow |
| PMV comfort | Fanger model from zone temperature and relative humidity |

Whole-building electricity is likewise derived as `Electricity:Building +
Electricity:HVAC`; this model exposes no `Electricity:Facility` meter.

## Tests

```bash
python -m pytest -q
```

## Layout

| Path | Responsibility |
| --- | --- |
| `backend/config/` | EnergyPlus discovery, runtime settings |
| `backend/simulation/` | Simulation thread, sensor reads, shared state |
| `backend/decision/` | Safety clamping of agent commands |
| `backend/mcp_server/` | MCP tools exposed to the agent |
| `backend/agent/` | LLM reasoning loop |
| `backend/api/` | FastAPI app and WebSocket stream |
| `backend/reports/` | Report generation |
| `models/` | Building models (`.idf`) under version control |
| `scripts/` | Environment verification and discovery tooling |
