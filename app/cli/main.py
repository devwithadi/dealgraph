import argparse
import json
from pathlib import Path

from app.cli.reporter import ConsoleReporter
from app.core.errors import AppError, report_cli_error
from app.core.logging import bind_request_id, configure_logging, new_request_id
from app.domain.enums import AIProvider
from app.pipeline.service import Pipeline


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dealgraph",
        description="DealGraph: evidence-backed seed investment triage",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="source startups and write investment memos")
    run.add_argument("--topic", required=True)
    run.add_argument("--batch")
    run.add_argument("--limit", type=_positive_int, help="optional emergency cap after date filtering")
    run.add_argument("--output", type=Path, default=Path("results"))
    run.add_argument("--source-file", type=Path)
    run.add_argument(
        "--deep-diligence",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="enable multi-hop 4-pillar deep diligence research (default: enabled, use --no-deep-diligence to opt out)",
    )
    run.add_argument("--max-hops", type=_positive_int, default=2, help="maximum research hops for deep diligence (default: 2)")
    run.add_argument("--json", action="store_true", help="print the machine-readable run summary")
    run.add_argument("--verbose", action="store_true", help="show operational logs on stderr")
    run.add_argument("--request-id", help="reuse an upstream request ID for end-to-end tracking")
    run.add_argument(
        "--provider",
        type=AIProvider,
        choices=list(AIProvider),
        default=AIProvider.BEDROCK,
        help="narrative provider (default: bedrock)",
    )
    run.add_argument("--model", help="default LLM model ID or alias for both screening and synthesis")
    run.add_argument("--screening-model", help="override LLM model ID or alias for screening")
    run.add_argument("--synthesis-model", help="override LLM model ID or alias for synthesis")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)
    request_id = "unbound"
    try:
        request_id = bind_request_id(args.request_id or new_request_id())
        reporter = None if args.json else ConsoleReporter()
        if args.command == "run":
            if args.source_file and not args.source_file.is_file():
                raise AppError(f"source file not found: {args.source_file}", exit_code=2)
            screening_model = args.screening_model or args.model
            synthesis_model = args.synthesis_model or args.model
            result = Pipeline().run(
                topic=args.topic,
                batch=args.batch,
                limit=args.limit,
                output=args.output,
                source_file=args.source_file,
                deep_diligence=args.deep_diligence,
                max_hops=args.max_hops,
                request_id=request_id,
                provider=args.provider,
                screening_model=screening_model,
                synthesis_model=synthesis_model,
                progress_callback=reporter,
            )
        else:
            raise AppError(f"unknown command: {args.command}", exit_code=2)
    except Exception as error:
        return report_cli_error(error, request_id)
    if args.json:
        print(json.dumps(result.model_dump(), indent=2))
    else:
        output_dir = Path(result.output)
        print(
            f"Screened {result.screened}/{result.candidates} companies; "
            f"created {result.succeeded}/{result.finalists} finalist memos; "
            f"selected {result.selected}."
        )
        print(f"PDF Memos: {output_dir}")
        print(f"Request ID: {result.request_id}")
        if result.succeeded > 0:
            print(f"\nTo open generated PDF investment memos:")
            print(f"  open {output_dir}/*.pdf")
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
