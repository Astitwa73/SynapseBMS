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

This model exposes no `Electricity:Facility` meter, so whole-building
electricity is derived. EnergyPlus meters electricity on two independent axes
and mixing them double-counts:

| Axis | Meters | Use |
| --- | --- | --- |
| System category (disjoint) | `Electricity:Building` + `Electricity:HVAC` + `Electricity:Plant` | Totalling |
| End use (disjoint) | Lights, Equipment, Fans, Cooling, Pumps | Attribution |

`Electricity:Plant` matters: this model cools through a chilled-water loop, so
the chiller and its pumps are metered under Plant rather than HVAC. Omitting it
hides the very energy the agent controls.

## Verify the control loop

```bash
python scripts/verify_control.py
```

Runs the same summer day twice, with and without a setpoint command, and reports
the difference. Expect roughly 30% cooling energy saved for a 2.1 °C setpoint
increase, at the cost of about 2 °C higher peak indoor temperature.

### Safety

The agent never writes to an actuator. Commands pass through `ControlStore`,
which clamps them at the boundary closest to the effect — the last component
before the actuator owns the invariant, because a limit enforced upstream can be
defeated by any bug downstream of it.

| Rule | Why |
| --- | --- |
| Cooling 22–28 °C, heating 16–20 °C | Comfort envelope |
| Heating ≤ cooling − 2 °C | **EnergyPlus terminates** on an inverted deadband, so a bad setpoint would end the demo |
| Max 0.5 °C change per timestep | Prevents HVAC surges and damps agent oscillation |
| Lighting ≥ 30% | Egress safety |
| No command → actuators released | Fail-safe: the building runs its own schedule |

Control state is sticky: an unset field means "leave this channel alone", not
"revert it". Only the absence of a command releases the actuators, so a decision
to hold does not hand the building back to its own schedule.

## Run autonomously

```bash
python scripts/run_autonomous.py --speed 0.05 --seconds 60
```

Simulation, comfort processing, decision policy and control running together
with no LLM. The agent sets back overnight, protects per-zone comfort during
occupied hours, and converts comfort headroom into savings.

### Comfort and air quality

PMV (ISO 7730 / ASHRAE 55) places thermal sensation on −3…+3, with ±0.5 as the
comfortable band. The model needs six inputs; this building measures two, and
the rest are explicit assumptions in `ComfortAssumptions` rather than literals
buried in the calculation. At 0.5 clo and 1.1 met the implementation puts
neutral at 25.4 °C, which matches the ASHRAE 55 summer comfort zone.

CO₂ is a steady-state mass balance over occupancy and ventilation mass flow.
It gives the equilibrium concentration, so it does not show the ramp as a room
fills.

### Decision policy

A priority ladder — first rule that applies decides. Ordering encodes intent.

| Priority | Condition | Action |
| --- | --- | --- |
| 1 | Unoccupied | Set back, dim lights |
| 2 | Any occupied zone PMV > +0.5 | Lower setpoint |
| 3 | Any occupied zone PMV < −0.5 | Raise setpoint |
| 4 | Comfortable with headroom | Raise setpoint, bank savings |
| 5 | Otherwise | Hold |

Rules 2 and 3 hold instead of acting when the setpoint is already at its limit:
relaxing a cooling setpoint stops cooling, it cannot add heat, so claiming
otherwise would be an action that does nothing.

`DecisionPolicy` is a Protocol, so the LLM policy drops in without inheriting
anything and the rule policy doubles as its runtime fallback.

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
