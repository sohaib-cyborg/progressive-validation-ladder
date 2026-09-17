"""Tests for settings loading (toolvalidator/config.py)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from toolvalidator.config import LLMSettings, StaticSettings, load_settings, parse_env_file


def test_defaults_with_empty_environment() -> None:
    s = load_settings(environ={}, env_file=None)
    assert s.llm.base_url == "https://llm.scads.ai/v1"
    assert s.llm.api_key is None
    assert s.llm.generator_model is None
    assert s.llm.judge_model is None
    assert s.sandbox.image == "python:3.12-slim"
    assert s.sandbox.mem_limit == "512m"
    assert s.sandbox.pids_limit == 128
    assert s.sandbox.timeout_s > 0
    assert s.sandbox.max_output_bytes == 1024 * 1024
    assert s.dataset_dir == Path("data/runbugrun_py")
    assert s.results_dir == Path("results")
    assert s.static.bandit_reject_severity == "HIGH"


def test_bandit_reject_severity_is_configurable() -> None:
    assert StaticSettings(bandit_reject_severity="MEDIUM").bandit_reject_severity == "MEDIUM"


def test_bandit_reject_severity_rejects_unknown_level() -> None:
    with pytest.raises(ValidationError):
        StaticSettings(bandit_reject_severity="CRITICAL")  # type: ignore[arg-type]


def test_reads_scads_values_from_environment() -> None:
    s = load_settings(
        environ={
            "SCADS_API_KEY": "sk-secret",
            "SCADS_BASE_URL": "https://example.invalid/v1",
            "SCADS_GENERATOR_MODEL": "gen-model",
            "SCADS_JUDGE_MODEL": "judge-model",
        },
        env_file=None,
    )
    assert s.llm.api_key is not None
    assert s.llm.api_key.get_secret_value() == "sk-secret"
    assert s.llm.base_url == "https://example.invalid/v1"
    assert s.llm.generator_model == "gen-model"
    assert s.llm.judge_model == "judge-model"


def test_api_key_never_appears_in_repr() -> None:
    s = load_settings(environ={"SCADS_API_KEY": "sk-secret"}, env_file=None)
    assert "sk-secret" not in repr(s)
    assert "sk-secret" not in s.model_dump_json()


def test_env_file_is_loaded_and_environment_wins(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("SCADS_API_KEY=from-file\nSCADS_JUDGE_MODEL=file-judge\n")
    s = load_settings(environ={"SCADS_JUDGE_MODEL": "env-judge"}, env_file=env_file)
    assert s.llm.api_key is not None
    assert s.llm.api_key.get_secret_value() == "from-file"
    assert s.llm.judge_model == "env-judge"


def test_missing_env_file_is_ignored(tmp_path: Path) -> None:
    s = load_settings(environ={}, env_file=tmp_path / "does-not-exist.env")
    assert s.llm.api_key is None


def test_empty_value_is_treated_as_unset() -> None:
    s = load_settings(environ={"SCADS_API_KEY": "", "SCADS_JUDGE_MODEL": ""}, env_file=None)
    assert s.llm.api_key is None
    assert s.llm.judge_model is None


def test_generator_and_judge_must_differ() -> None:
    with pytest.raises(ValidationError):
        LLMSettings(generator_model="same", judge_model="same")


def test_parse_env_file_handles_comments_quotes_and_equals() -> None:
    text = "# comment\n\nA=1\nB = \"two words\"\nC='x=y'\nexport D=4\n"
    assert parse_env_file(text) == {"A": "1", "B": "two words", "C": "x=y", "D": "4"}


def test_parse_env_file_rejects_malformed_line() -> None:
    with pytest.raises(ValueError, match="line 2"):
        parse_env_file("A=1\nnot a pair\n")
