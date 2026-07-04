from __future__ import annotations

import argparse
from pathlib import Path

from src.script_report import ScriptReportOptions, ScriptReportRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a polished commentary report from final football events")
    parser.add_argument("--events", required=True, help="Path to final_events.json")
    parser.add_argument("--out", default="outputs_script_report", help="Output directory")
    parser.add_argument("--match-info", default=None, help="Optional match info JSON")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=10000, help="Max output tokens for the report")
    parser.add_argument("--report-version", choices=["v2", "v3", "v3_markdown"], default="v2", help="Report output schema")
    parser.add_argument("--pure-model-output", action="store_true", help="Write report content directly from the model")
    parser.add_argument("--no-model", action="store_true", help="Write deterministic fallback report without API")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    options = ScriptReportOptions(
        events_path=Path(args.events),
        out_dir=Path(args.out),
        match_info_path=Path(args.match_info) if args.match_info else None,
        temperature=args.temperature,
        max_tokens=max(1, args.max_tokens),
        report_version=args.report_version,
        pure_model_output=args.pure_model_output,
        no_model=args.no_model,
    )
    result = ScriptReportRunner(options).run()
    print(f"Done. Script report outputs written to: {result}")


if __name__ == "__main__":
    main()
