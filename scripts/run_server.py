"""Start the backend: simulation, agent and API together.

    python scripts/run_server.py
    python scripts/run_server.py --policy llm --speed 0.4 --decide-every 12

The building starts with the server and stops with it, so there is one process
and one lifecycle rather than a server and a separately-managed simulation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn  # noqa: E402

from backend.api.app import create_app  # noqa: E402
from backend.config.logging import configure_logging  # noqa: E402
from backend.config.settings import DEFAULT_MODEL_NAME, CalendarDay  # noqa: E402
from backend.services.building_service import ServiceConfig, check_llm_available  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--model", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--policy", choices=("rule", "llm"), default="rule")
    parser.add_argument("--llm-model", default="llama3")
    parser.add_argument("--speed", type=float, default=0.4,
                        help="wall-clock seconds per simulated timestep")
    parser.add_argument("--decide-every", type=int, default=12,
                        help="timesteps per agent decision")
    parser.add_argument("--from-date", default="07-02")
    args = parser.parse_args()

    configure_logging()

    if args.policy == "llm":
        problem = check_llm_available(args.llm_model)
        if problem:
            print(f"FAIL: {problem}")
            return 1

    month, day = (int(part) for part in args.from_date.split("-"))
    config = ServiceConfig(
        model_name=args.model,
        policy=args.policy,
        llm_model=args.llm_model,
        seconds_per_timestep=args.speed,
        timesteps_per_decision=args.decide_every,
        start_date=CalendarDay(month=month, day=day),
    )

    print(f"API      http://{args.host}:{args.port}")
    print(f"Docs     http://{args.host}:{args.port}/docs")
    print(f"Stream   ws://{args.host}:{args.port}/ws")
    print(f"Policy   {args.policy}" + (f" ({args.llm_model})" if args.policy == "llm" else ""))
    print()

    uvicorn.run(create_app(config), host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
