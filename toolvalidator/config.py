"""Settings: LLM endpoint + models, sandbox limits, dataset/result paths.

Values come from the process environment, falling back to a ``.env`` file
(environment wins). No defaults are invented for things we don't know yet:
model IDs must be set explicitly, and score thresholds are added only once S6
fits them from data.
"""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

DEFAULT_ENV_FILE = Path(".env")

type Severity = Literal["LOW", "MEDIUM", "HIGH"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LLMSettings(_Frozen):
    base_url: str = "https://llm.scads.ai/v1"
    api_key: SecretStr | None = None
    generator_model: str | None = None
    judge_model: str | None = None
    # Reasoning models (the judge) can take minutes on long prompts.
    timeout_s: float = Field(default=300.0, gt=0)
    max_retries: int = Field(default=3, ge=0)
    # SCADS throttles per key and model (judge: 3,000 tokens per ~60 s window, measured
    # 2026-09-24). On HTTP 429 the client waits for the stated reset, this many times.
    rate_limit_waits: int = Field(default=10, ge=0)
    max_rate_limit_wait_s: float = Field(default=120.0, gt=0)
    # Reasoning counts as completion. One GLM-5.3-Flash comparison ran away to 11,860 tokens
    # (2026-09-26), more than a whole rate-limit window; a capped reply that is cut off
    # raises LLMOutputError instead of being parsed.
    max_completion_tokens: int = Field(default=8192, gt=0)  # judge role
    # The generator's window is 40,000 tokens; 2 of 50 RQ3 dev generations exceeded 8,192.
    generator_max_completion_tokens: int = Field(default=16384, gt=0)

    @model_validator(mode="after")
    def _judge_is_independent(self) -> Self:
        if self.generator_model is not None and self.generator_model == self.judge_model:
            raise ValueError("judge_model must differ from generator_model")
        return self


class SandboxSettings(_Frozen):
    # Limits match the config verified by docker_probe.py.
    # Built from toolvalidator/sandbox/Dockerfile (python:3.12-slim + numpy + mutmut).
    image: str = "toolvalidator-sandbox:py3.12"
    mem_limit: str = "512m"
    pids_limit: int = Field(default=128, gt=0)
    timeout_s: float = Field(default=10.0, gt=0)
    # Per stream (stdout, stderr). Largest RunBugRun expected output is ~180 KB.
    max_output_bytes: int = Field(default=1024 * 1024, gt=0)


class ExecutionSettings(_Frozen):
    # S4. 10s per test: 4 of 9 pilot false rejections were slow-but-correct programs.
    # Float tolerance: expected outputs are rounded while Python prints full precision.
    test_timeout_s: float = Field(default=10.0, gt=0)
    float_rel_tol: float = Field(default=1e-6, gt=0)
    float_abs_tol: float = Field(default=1e-6, ge=0)


class StaticSettings(_Frozen):
    # S2 hard-rejects at or above this bandit severity. All findings are recorded
    # regardless, so experiments can re-threshold offline (DECISIONS.md).
    bandit_reject_severity: Severity = "HIGH"


class Settings(_Frozen):
    llm: LLMSettings = Field(default_factory=LLMSettings)
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)
    static: StaticSettings = Field(default_factory=StaticSettings)
    execution: ExecutionSettings = Field(default_factory=ExecutionSettings)
    dataset_dir: Path = Path("data/runbugrun_py")
    results_dir: Path = Path("results")


def parse_env_file(text: str) -> dict[str, str]:
    """Parse ``KEY=value`` lines. Blank lines and ``#`` comments are skipped.

    Raises ValueError (with the line number) on a line that isn't a pair.
    """
    values: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").lstrip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not key:
            raise ValueError(f".env line {lineno} is not KEY=value")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def load_settings(
    environ: Mapping[str, str] | None = None,
    env_file: Path | None = DEFAULT_ENV_FILE,
) -> Settings:
    """Build Settings from ``environ`` (default: os.environ) over ``env_file``."""
    merged: dict[str, str] = {}
    if env_file is not None and env_file.is_file():
        merged.update(parse_env_file(env_file.read_text(encoding="utf-8")))
    merged.update(os.environ if environ is None else environ)

    def get(name: str) -> str | None:
        return merged.get(name) or None  # empty string counts as unset

    llm = LLMSettings(
        base_url=get("SCADS_BASE_URL") or LLMSettings().base_url,
        api_key=SecretStr(key) if (key := get("SCADS_API_KEY")) else None,
        generator_model=get("SCADS_GENERATOR_MODEL"),
        judge_model=get("SCADS_JUDGE_MODEL"),
    )
    return Settings(llm=llm)
