"""Shared fixtures. The fake sandbox never executes code (CLAUDE.md §7)."""

import pytest

from toolvalidator.contracts import CapabilityRequest, ExecResult, IOExample, ValidationRecord


class FakeSandbox:
    """Records every ``run`` call and returns a canned result. Executes nothing."""

    def __init__(self, result: ExecResult | None = None) -> None:
        self.result = result or ExecResult(stdout="", stderr="", exit_code=0, duration_s=0.0)
        self.calls: list[tuple[str, str, float | None]] = []

    def run(self, script: str, *, stdin: str = "", timeout_s: float | None = None) -> ExecResult:
        self.calls.append((script, stdin, timeout_s))
        return self.result


@pytest.fixture
def fake_sandbox() -> FakeSandbox:
    return FakeSandbox()


@pytest.fixture
def record() -> ValidationRecord:
    return ValidationRecord(
        request=CapabilityRequest(
            name="celsius_to_fahrenheit",
            description="Convert a temperature in Celsius to Fahrenheit.",
            examples=[IOExample(input=100, output=212)],
        )
    )
