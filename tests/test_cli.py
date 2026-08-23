import json
from pathlib import Path

from app.cli.main import build_parser, main
from app.core.errors import AppError
from app.domain.enums import AIProvider
from app.domain.models import RunSummary


def summary(tmp_path: Path, *, failed: int = 0) -> RunSummary:
    return RunSummary(
        run_id="run-1",
        request_id="req-test",
        output=str(tmp_path),
        candidates=25,
        screened=25,
        finalists=3,
        selected=2,
        succeeded=3 - failed,
        failed=failed,
    )


def test_cli_defaults_to_bedrock_without_a_company_cap() -> None:
    default = build_parser().parse_args(["run", "--topic", "AI"])
    openai = build_parser().parse_args(["run", "--topic", "AI", "--provider", "openai"])
    capped = build_parser().parse_args(["run", "--topic", "AI", "--limit", "50"])

    assert default.provider is AIProvider.BEDROCK
    assert default.limit is None
    assert openai.provider is AIProvider.OPENAI
    assert capped.limit == 50


def test_cli_reports_screening_and_finalist_counts(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr("app.cli.main.new_request_id", lambda: "req-test")
    monkeypatch.setattr("app.cli.main.Pipeline.run", lambda *_args, **_kwargs: summary(tmp_path))

    assert main(["run", "--topic", "AI"]) == 0
    output = capsys.readouterr().out
    assert "Screened 25/25 companies; created 3/3 finalist memos; selected 2." in output
    assert f"Memos: {tmp_path / 'memos'}" in output


def test_cli_json_output_contains_stage_counts(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr("app.cli.main.new_request_id", lambda: "req-test")
    monkeypatch.setattr("app.cli.main.Pipeline.run", lambda *_args, **_kwargs: summary(tmp_path))

    assert main(["run", "--topic", "AI", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["screened"] == 25
    assert payload["finalists"] == 3


def test_cli_centralizes_expected_errors(monkeypatch, capsys) -> None:
    monkeypatch.setattr("app.cli.main.new_request_id", lambda: "req-test")

    def fail(*_args, **_kwargs):
        raise AppError("candidate source unavailable", exit_code=3)

    monkeypatch.setattr("app.cli.main.Pipeline.run", fail)
    assert main(["run", "--topic", "AI"]) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Error [req-test]: candidate source unavailable\n"


def test_missing_source_file_uses_central_error_boundary(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "missing.json"
    assert main(["run", "--topic", "AI", "--source-file", str(missing), "--request-id", "req-missing"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"Error [req-missing]: source file not found: {missing}\n"


def test_cli_returns_failure_when_any_candidate_fails(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr("app.cli.main.new_request_id", lambda: "req-test")
    monkeypatch.setattr("app.cli.main.Pipeline.run", lambda *_args, **_kwargs: summary(tmp_path, failed=1))
    assert main(["run", "--topic", "AI"]) == 1
