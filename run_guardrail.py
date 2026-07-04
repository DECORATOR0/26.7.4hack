from __future__ import annotations

import argparse
from pathlib import Path

from src.guardrail import GuardrailOptions, V4GuardrailRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run V4 single-pass guardrail over final events")
    parser.add_argument("--events", required=True, help="Path to final_events.json")
    parser.add_argument("--out", default="outputs_event_agent_v4", help="Output directory")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=6000)
    parser.add_argument("--no-model", action="store_true", help="Only apply deterministic safe patches")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    options = GuardrailOptions(
        events_path=Path(args.events),
        out_dir=Path(args.out),
        temperature=args.temperature,
        max_tokens=max(1, args.max_tokens),
        no_model=args.no_model,
    )
    result = V4GuardrailRunner(options).run()
    print(f"Done. V4 guardrail outputs written to: {result}")


if __name__ == "__main__":
    main()
