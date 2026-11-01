from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_bedrock_runtime_dependency_is_installed_with_litellm() -> None:
    dependencies = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["dependencies"]

    assert any(dependency.startswith("litellm") for dependency in dependencies)
    assert any(dependency.startswith("boto3") for dependency in dependencies)


def test_prompts_are_segregated_by_llm_stage() -> None:
    prompt_root = ROOT / "app" / "prompts"
    assert {
        path.name for path in prompt_root.iterdir() if path.name != "__pycache__"
    } == {"__init__.py", "diligence", "screening", "synthesis"}

    for stage in ("diligence", "screening", "synthesis"):
        assert {
            path.name
            for path in (prompt_root / stage).iterdir()
            if path.name != "__pycache__"
        } == {"__init__.py", "persona.py", "workflow.py", "output.py", "guardrails.py"}


def test_primary_and_legacy_cli_names_target_the_same_entrypoint() -> None:
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'dealgraph = "app.cli.main:main"' in project
    assert 'ida = "app.cli.main:main"' in project


def test_env_example_documents_bedrock_without_containing_a_key() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "AWS_BEARER_TOKEN_BEDROCK=\n" in example
    assert "AWS_REGION=us-east-1" in example
    assert "BEDROCK_SCREENING_MODEL_ID=" in example
    assert "BEDROCK_MODEL_ID=" in example


def test_submission_docs_describe_the_live_pdf_pipeline() -> None:
    docs = {
        "doc/README.md": (ROOT / "doc" / "README.md").read_text(encoding="utf-8"),
        "doc/pipeline-data-flow.html": (ROOT / "doc" / "pipeline-data-flow.html").read_text(encoding="utf-8"),
        "doc/system-architecture.html": (ROOT / "doc" / "system-architecture.html").read_text(encoding="utf-8"),
    }

    for name, content in docs.items():
        lowered = content.lower()
        assert "replay" not in lowered, name
        assert "--offline" not in content, name

    assert "PDF" in docs["doc/README.md"]
    assert "one-page PDF" in docs["doc/pipeline-data-flow.html"]
    assert "PDF" in docs["doc/system-architecture.html"]


def test_readme_links_deep_architecture_diagrams() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    architecture = (ROOT / "doc" / "system-architecture.html").read_text(
        encoding="utf-8"
    )
    data_flow = (ROOT / "doc" / "pipeline-data-flow.html").read_text(
        encoding="utf-8"
    )

    assert "doc/system-architecture.html" in readme
    assert "doc/pipeline-data-flow.html" in readme
    assert "app/pipeline/service.py" in architecture
    assert "Per-company failure isolation" in architecture
    assert "X-Kong-Request-ID" in data_flow
    assert "LiteLLM" in data_flow
    assert "SSRF" in data_flow
    assert "atomic" in data_flow
