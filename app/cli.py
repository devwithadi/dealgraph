"""The only supported user interface."""

import argparse
import json
from pathlib import Path

from app.pipeline import Pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI-augmented seed investment triage")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="source startups and write investment memos")
    run.add_argument("--topic", required=True)
    run.add_argument("--batch")
    run.add_argument("--limit", type=int, default=10, choices=range(1, 21))
    run.add_argument("--output", type=Path, default=Path("data/runs/latest"))
    run.add_argument("--source-file", type=Path)
    run.add_argument("--offline", action="store_true", help="replay source data without web enrichment")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.source_file and not args.source_file.is_file():
        build_parser().error(f"source file not found: {args.source_file}")
    result = Pipeline().run(
        topic=args.topic,
        batch=args.batch,
        limit=args.limit,
        output=args.output,
        source_file=args.source_file,
        offline=args.offline,
    )
    print(json.dumps(result.model_dump(), indent=2))
    return 0 if result.succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
