import json
import subprocess
import sys
from pathlib import Path

from app.cli import main


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
    summary = json.loads(completed.stdout)
    assert summary["succeeded"] == 1
    assert list((tmp_path / "memos").glob("*.md"))


def test_cli_main_emits_json_summary(tmp_path: Path, capsys) -> None:
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
        ]
    )

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["output"] == str(tmp_path.resolve())
    assert summary["succeeded"] == 1
