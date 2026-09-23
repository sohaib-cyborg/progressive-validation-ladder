"""Tests for the shared pipeline contracts (toolvalidator/contracts.py)."""

import pytest
from pydantic import ValidationError

from tests.conftest import FakeSandbox
from toolvalidator.contracts import (
    CapabilityRequest,
    ExecResult,
    FailureReport,
    IOExample,
    ParamSpec,
    Sandbox,
    StageResult,
    ToolArtifact,
    ValidationRecord,
    Verdict,
)


def _request() -> CapabilityRequest:
    return CapabilityRequest(
        name="celsius_to_fahrenheit",
        capability="celsius_to_fahrenheit",
        description="Convert a temperature in Celsius to Fahrenheit.",
        inputs=[ParamSpec(name="celsius", type="number", description="Degrees Celsius")],
        outputs=[ParamSpec(name="fahrenheit", type="number", description="Degrees Fahrenheit")],
        rationale="The task needs a unit conversion no available tool provides.",
    )


# --- CapabilityRequest / ParamSpec ---------------------------------------------


def test_capability_request_carries_the_upstream_fields() -> None:
    req = _request()
    assert req.name == "celsius_to_fahrenheit"
    assert req.capability == "celsius_to_fahrenheit"
    assert (req.inputs[0].name, req.inputs[0].type) == ("celsius", "number")
    assert req.outputs[0].name == "fahrenheit"
    assert req.rationale is not None


def test_inputs_outputs_default_empty_and_rationale_optional() -> None:
    # Upstream defaults (docs/capability_request.md §2): inputs/outputs [], rationale None.
    req = CapabilityRequest(name="t", capability="t", description="d")
    assert req.inputs == [] and req.outputs == [] and req.rationale is None


def test_upstream_json_loads_unchanged() -> None:
    # Verbatim shape emitted by the capability matcher (docs/capability_request.md §2).
    payload = {
        "name": "realtime_weather",
        "capability": "realtime_weather",
        "description": "Fetch current weather conditions from a live weather API",
        "inputs": [{"name": "location", "type": "string", "description": "City or region"}],
        "outputs": [
            {"name": "temperature", "type": "string", "description": "Current temperature"},
            {"name": "condition", "type": "string", "description": "Weather condition"},
        ],
        "rationale": "The task requires accessing real-time weather data.",
    }
    req = CapabilityRequest.model_validate(payload)
    assert [p.name for p in req.outputs] == ["temperature", "condition"]
    assert req.inputs[0].required is True  # required unless the payload says otherwise


def test_param_spec_required_flag_round_trips() -> None:
    payload = {"name": "q", "type": "string", "description": "d", "required": False}
    assert ParamSpec.model_validate(payload).required is False


def test_capability_request_requires_name_capability_and_description() -> None:
    for payload in (
        {"capability": "c", "description": "d"},
        {"name": "n", "description": "d"},
        {"name": "n", "capability": "c"},
        {"name": "", "capability": "c", "description": "d"},
        {"name": "n", "capability": "", "description": "d"},
    ):
        with pytest.raises(ValidationError):
            CapabilityRequest.model_validate(payload)


def test_capability_request_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        CapabilityRequest.model_validate(
            {"name": "t", "capability": "t", "description": "d", "examples": []}
        )


def test_io_example_covers_both_tool_shapes() -> None:
    # IOExample is a TEST CASE now, not part of the request: stdin/stdout or typed args.
    assert IOExample(input="0\n", output="32\n").output == "32\n"
    typed = IOExample(input={"celsius": 100}, output={"fahrenheit": 212})
    assert typed.input == {"celsius": 100}


def test_capability_request_is_immutable() -> None:
    req = _request()
    with pytest.raises(ValidationError):
        req.name = "other"  # type: ignore[misc]


# --- ToolArtifact --------------------------------------------------------------


def test_tool_artifact_defaults_metadata() -> None:
    art = ToolArtifact(tool_id="t1", code="def f() -> int:\n    return 1\n")
    assert art.metadata == {}


def test_tool_artifact_accepts_empty_code() -> None:
    # Empty/garbage code is a *stage* failure (S1), not a contract violation.
    assert ToolArtifact(tool_id="t1", code="").code == ""


def test_tool_artifact_keeps_synthesis_metadata() -> None:
    art = ToolArtifact(tool_id="t1", code="", metadata={"confidence": 0.9, "retries": 2})
    assert art.metadata["retries"] == 2


# --- StageResult ---------------------------------------------------------------


def test_stage_result_minimal_pass() -> None:
    res = StageResult(stage="s1_parse", passed=True)
    assert res.category is None
    assert res.detail == ""
    assert res.data == {}


def test_stage_result_failure_with_data() -> None:
    res = StageResult(
        stage="s1_parse",
        passed=False,
        category="syntax_error",
        detail="invalid syntax",
        data={"line": 3},
    )
    assert not res.passed
    assert res.data["line"] == 3


def test_stage_result_rejects_empty_stage() -> None:
    with pytest.raises(ValidationError):
        StageResult(stage="", passed=True)


# --- FailureReport -------------------------------------------------------------


def test_failure_report_line_optional() -> None:
    rep = FailureReport(stage="s2_static", category="dangerous_call", message="eval used")
    assert rep.line is None


def test_failure_report_rejects_non_positive_line() -> None:
    with pytest.raises(ValidationError):
        FailureReport(stage="s1_parse", category="syntax_error", message="x", line=0)


# --- Verdict -------------------------------------------------------------------


def test_verdict_values() -> None:
    assert {v.value for v in Verdict} == {"ACCEPT", "REJECT", "NEEDS_REVIEW"}
    assert Verdict("REJECT") is Verdict.REJECT


# --- ValidationRecord ----------------------------------------------------------


def test_record_starts_undecided() -> None:
    rec = ValidationRecord(request=_request())
    assert rec.results == []
    assert rec.failures == []
    assert rec.verdict is None


def test_record_add_appends_and_returns_same_result() -> None:
    rec = ValidationRecord(request=_request())
    first = StageResult(stage="s1_parse", passed=True)
    second = StageResult(stage="s2_static", passed=False, category="dangerous_call")
    assert rec.add(first) is first
    assert rec.add(second) is second
    assert rec.results == [first, second]


def test_record_json_round_trip() -> None:
    rec = ValidationRecord(request=_request())
    rec.add(StageResult(stage="s1_parse", passed=False, category="syntax_error", data={"a": [1]}))
    rec.failures.append(
        FailureReport(stage="s1_parse", category="syntax_error", message="bad", line=2)
    )
    rec.verdict = Verdict.REJECT
    restored = ValidationRecord.model_validate_json(rec.model_dump_json())
    assert restored == rec
    assert restored.verdict is Verdict.REJECT


# --- ExecResult / Sandbox ------------------------------------------------------


def test_exec_result_defaults_not_timed_out() -> None:
    res = ExecResult(stdout="hi\n", stderr="", exit_code=0, duration_s=0.01)
    assert res.timed_out is False


def test_exec_result_rejects_negative_duration() -> None:
    with pytest.raises(ValidationError):
        ExecResult(stdout="", stderr="", exit_code=0, duration_s=-1.0)


def test_fake_sandbox_satisfies_sandbox_protocol(fake_sandbox: FakeSandbox) -> None:
    assert isinstance(fake_sandbox, Sandbox)


def test_fake_sandbox_records_calls_and_never_executes(fake_sandbox: FakeSandbox) -> None:
    out = fake_sandbox.run("raise SystemExit(3)", stdin="1\n", timeout_s=2.0)
    assert out.exit_code == 0  # canned result: the script was not run
    assert fake_sandbox.calls == [("raise SystemExit(3)", "1\n", 2.0)]
