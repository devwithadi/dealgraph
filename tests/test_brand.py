import tomllib
from pathlib import Path

from app.cli.main import build_parser
from app.core.logging import USER_AGENT, configure_logging


ROOT = Path(__file__).parents[1]


def test_dealgraph_is_the_primary_project_identity() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]

    assert project["name"] == "dealgraph"
    assert project["scripts"]["dealgraph"] == "app.cli.main:main"
    assert project["scripts"]["ida"] == "app.cli.main:main"
    assert build_parser().prog == "dealgraph"
    assert "DealGraph" in build_parser().description
    assert USER_AGENT.startswith("DealGraph/")
    assert configure_logging().name == "dealgraph"
    assert (ROOT / "README.md").read_text().startswith("# DealGraph\n")


def test_agent_guide_documents_project_specific_workflow() -> None:
    guide = (ROOT / "AGENTS.md").read_text()

    assert "DealGraph" in guide
    assert "uv run pytest" in guide
    assert "X-Kong-Request-ID" in guide
    assert "PitchBook" in guide
    assert "80%" in guide
    assert "Mandatory ECC harness" in guide
    assert "$ponytail" in guide
