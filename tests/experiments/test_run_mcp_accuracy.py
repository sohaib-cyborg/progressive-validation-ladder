"""Tests for the RQ5 runner (experiments/run_mcp_accuracy.py).

Synthetic tools only; none of it is a result.
"""

import ast
import json
from typing import Any

import pytest
from pydantic import JsonValue

from data.loaders.mcp_tools import McpTool
from experiments.run_mcp_accuracy import (
    McpRow,
    ToolScore,
    evaluate_llm,
    score_schema,
    signature_schema,
    strip_hints,
    summarize,
)
from toolvalidator.llm.scads_client import LLMResult

CODE = '''import json


def convert(amount: float, currency: str = "EUR", rounded: bool = False) -> str:
    """Converts an amount."""
    total: float = amount * 2
    return json.dumps(total)
'''
STRING_RESULT: dict[str, JsonValue] = {
    "type": "object", "properties": {"result": {"title": "Result", "type": "string"}},
    "required": ["result"], "title": "convertOutput",
}  # fmt: skip
REFERENCE = McpTool(
    name="convert",
    description="Converts an amount.",
    code=CODE,
    input_schema={
        "type": "object",
        "title": "convertArguments",
        "properties": {
            "amount": {"title": "Amount", "type": "number"},
            "currency": {"title": "Currency", "type": "string", "default": "EUR"},
            "rounded": {"title": "Rounded", "type": "boolean", "default": False},
        },
        "required": ["amount"],
    },
    output_schema=STRING_RESULT,
)


def _schema(properties: dict[str, Any], required: list[str], output: Any = None) -> dict[str, Any]:
    return {
        "name": "convert",
        "inputSchema": {"type": "object", "properties": properties, "required": required},
        "outputSchema": output if output is not None else
        {"type": "object", "properties": {"text": {"type": "string"}}},
    }  # fmt: skip


# --- the signature baseline and hint stripping ------------------------------------------


def test_signature_baseline_reads_hints_and_defaults() -> None:
    schema = signature_schema(CODE, "convert")
    score = score_schema(schema, REFERENCE)
    assert score.exact and score.output_exact
    assert schema["inputSchema"]["required"] == ["amount"]  # type: ignore[index, call-overload]


def test_strip_hints_removes_every_annotation_and_keeps_behaviour_text() -> None:
    stripped = strip_hints(CODE)
    tree = ast.parse(stripped)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef))
    assert all(a.annotation is None for a in fn.args.args) and fn.returns is None
    assert not any(isinstance(n, ast.AnnAssign) for n in ast.walk(tree))
    assert '"EUR"' in stripped or "'EUR'" in stripped
    assert "Converts an amount." in stripped


# --- scoring against the reference -----------------------------------------------------------


def test_a_perfect_schema_scores_full_marks() -> None:
    perfect = _schema(
        {"amount": {"type": "number"}, "currency": {"type": "string", "default": "EUR"},
         "rounded": {"type": "boolean", "default": False}},
        ["amount"], output={"type": "object", "properties": {"result": {"type": "string"}},
                            "required": ["result"]},
    )  # fmt: skip
    score = score_schema(perfect, REFERENCE)
    assert score == ToolScore(valid=True, precision=1.0, recall=1.0, f1=1.0, type_accuracy=1.0,
                              required_accuracy=1.0, complete=True, exact=True, output_ok=True,
                              output_exact=True)  # fmt: skip


def test_wrong_type_missing_parameter_and_extra_parameter_are_counted() -> None:
    schema = _schema(
        {"amount": {"type": "integer"}, "currency": {"type": "string"},
         "extra": {"type": "string"}},
        ["amount", "currency"],
    )  # fmt: skip
    score = score_schema(schema, REFERENCE)
    assert (score.precision, score.recall) == (2 / 3, 2 / 3)
    assert score.type_accuracy == 0.5  # amount: integer vs number
    assert score.required_accuracy == 0.5  # currency wrongly required
    assert not score.complete and not score.exact
    assert score.output_ok and not score.output_exact  # one string field, not named "result"


def test_no_parameters_on_both_sides_is_full_recall() -> None:
    reference = REFERENCE.model_copy(update={"input_schema": {"type": "object", "properties": {}}})
    score = score_schema(_schema({}, []), reference)
    assert (score.precision, score.recall, score.f1) == (1.0, 1.0, 1.0)
    assert score.type_accuracy is None and score.exact


def test_an_invalid_schema_is_scored_but_marked_invalid() -> None:
    score = score_schema(_schema({"amount": {"type": "float"}}, ["amount"]), REFERENCE)
    assert not score.valid


# --- the LLM conditions ------------------------------------------------------------------------


class _Client:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.users: list[str] = []

    def complete(self, role: str, *, system: str, user: str) -> LLMResult:
        self.users.append(user)
        return LLMResult(model="m", content=self.reply, reasoning=None, prompt_tokens=3,
                         completion_tokens=4, latency_s=0.0)  # fmt: skip


def test_llm_condition_sends_name_and_description_only_and_scores_the_reply() -> None:
    client: Any = _Client(json.dumps(signature_schema(CODE, "convert")))
    row = evaluate_llm(REFERENCE, "llm_stripped", 2, client)
    assert row.condition == "llm_stripped" and row.run == 2 and row.error is None
    assert row.score is not None and row.score.exact
    [user] = client.users
    assert "Declared inputs" not in user  # the request does not hand over the answer
    assert "amount: float" not in user  # hints stripped in this condition


def test_an_unusable_llm_reply_is_an_error_row() -> None:
    row = evaluate_llm(REFERENCE, "llm_hints", 0, _Client("no json"))  # type: ignore[arg-type]
    assert row.error is not None and row.score is None


# --- summary -------------------------------------------------------------------------------------


def _row(tool: str, condition: str, run: int, f1: float, schema: dict[str, Any]) -> McpRow:
    score = ToolScore(valid=True, precision=f1, recall=f1, f1=f1, type_accuracy=1.0,
                      required_accuracy=1.0, complete=f1 == 1.0, exact=f1 == 1.0,
                      output_ok=True, output_exact=False)  # fmt: skip
    return McpRow(tool=tool, condition=condition, run=run, generated=schema, error=None,
                  score=score, n_params=2, loc=5)  # fmt: skip


def test_summary_means_errors_and_run_to_run_agreement() -> None:
    a, b = _schema({"x": {"type": "string"}}, ["x"]), _schema({"y": {"type": "string"}}, ["y"])
    rows = [
        _row("t1", "llm_hints", 0, 1.0, a), _row("t1", "llm_hints", 1, 1.0, a),
        _row("t2", "llm_hints", 0, 0.5, a), _row("t2", "llm_hints", 1, 0.5, b),
        McpRow(tool="t3", condition="llm_hints", run=0, generated=None, error="LLMOutputError",
               score=None, n_params=1, loc=3),
    ]  # fmt: skip
    summary = summarize(rows)
    hints = summary["conditions"]["llm_hints"]  # type: ignore[index, call-overload]
    assert hints["rows"] == 5 and hints["errors"] == 1
    assert hints["f1"] == pytest.approx(0.75)
    assert hints["exact"] == pytest.approx(0.5)
    assert hints["runs_identical"] == {"tools": 2, "identical": 1}
