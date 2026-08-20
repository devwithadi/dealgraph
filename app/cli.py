"""The only supported user interface."""

import argparse
import json
from pathlib import Path

from app.errors import AppError, report_cli_error
from app.logging import bind_request_id, configure_logging, new_request_id
from app.pipeline import Pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dealgraph",
        description="DealGraph: evidence-backed seed investment triage",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="source startups and write investment memos")
    run.add_argument("--topic", required=True)
    run.add_argument("--batch")
    run.add_argument("--limit", type=int, default=10, choices=range(1, 21))
    run.add_argument("--output", type=Path, default=Path("data/runs/latest"))
    run.add_argument("--source-file", type=Path)
    run.add_argument("--offline", action="store_true", help="replay source data without web enrichment")
    run.add_argument("--json", action="store_true", help="print the machine-readable run summary")
    run.add_argument("--verbose", action="store_true", help="show operational logs on stderr")
    run.add_argument("--request-id", help="reuse an upstream request ID for end-to-end tracking")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    request_id = "unbound"
    try:
        request_id = bind_request_id(args.request_id or new_request_id())
        if args.source_file and not args.source_file.is_file():
            raise AppError(f"source file not found: {args.source_file}", exit_code=2)
        result = Pipeline().run(
            topic=args.topic,
            batch=args.batch,
            limit=args.limit,
            output=args.output,
            source_file=args.source_file,
            offline=args.offline,
            request_id=request_id,
        )
    except Exception as error:
        return report_cli_error(error, request_id)
    if args.json:
        print(json.dumps(result.model_dump(), indent=2))
    else:
        print(f"Completed {result.succeeded}/{result.candidates} companies.")
        print(f"Memos: {Path(result.output) / 'memos'}")
        print(f"Request ID: {result.request_id}")
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
