import subprocess
import sys
from pathlib import Path

from app.cli import main
from app.errors import AppError


FIXTURE = Path(__file__).parent / "fixtures" / "yc.json"


def test_cli_offline_replay_creates_memos(tmp_path: Path) -> None:
    command = [
        sys.executable,
        "-m",
        "app.cli",
        "run",
        "--topic",
        "AI agents for SMBs",
        "--batch",
        "W25",
        "--limit",
        "1",
        "--source-file",
        str(FIXTURE),
        "--offline",
        "--output",
        str(tmp_path),
    ]
    completed = subprocess.run(command, text=True, capture_output=True, check=False, timeout=15)
    assert completed.returncode == 0, completed.stderr
    lines = completed.stdout.splitlines()
    assert lines[:2] == [
        "Completed 1/1 companies.",
        f"Memos: {(tmp_path / 'memos').resolve()}",
    ]
    assert len(lines) == 3
    assert lines[2].startswith("Request ID: req-")
    assert completed.stderr == ""
    assert list((tmp_path / "memos").glob("*.md"))


def test_cli_main_emits_json_only_when_requested(tmp_path: Path, capsys) -> None:
    exit_code = main(
        [
            "run",
            "--topic",
            "AI agents for SMBs",
            "--batch",
            "W25",
            "--limit",
            "1",
            "--source-file",
            str(FIXTURE),
            "--offline",
            "--output",
            str(tmp_path),
            "--json",
        ]
    )

    assert exit_code == 0
    import json

    summary = json.loads(capsys.readouterr().out)
    assert summary["output"] == str(tmp_path.resolve())
    assert summary["succeeded"] == 1
    assert summary["request_id"].startswith("req-")


def test_cli_centralizes_expected_errors(monkeypatch, capsys) -> None:
    monkeypatch.setattr("app.cli.new_request_id", lambda: "req-test")

    def fail(*_args, **_kwargs):
        raise AppError("candidate source unavailable", exit_code=3)

    monkeypatch.setattr("app.cli.Pipeline.run", fail)
    exit_code = main(["run", "--topic", "AI", "--offline"])

    captured = capsys.readouterr()
    assert exit_code == 3
    assert captured.out == ""
    assert captured.err == "Error [req-test]: candidate source unavailable\n"
    assert "Traceback" not in captured.err
