"""RQ5: can accurate MCP schemas be generated from code + request? Scored on real tools.

    python -m experiments.run_mcp_accuracy --project-b <path to Project B> --out results/rq5

Benchmark: the 23 tools of Project B's FastMCP server, with the schemas that server really
sent (``data/loaders/mcp_tools.py``; copied to the git-ignored ``data/mcp_tools/``).
Conditions, all on every tool:
1. ``signature`` — no LLM: read the type hints with ``ast`` and apply FastMCP's rules
   (a default makes a parameter optional; a non-object return becomes ``{"result": T}``).
2. ``llm_hints`` — S7 (``generate_mcp_schema@v1``) on the code as written.
3. ``llm_stripped`` — S7 on the same code with every type annotation removed.
The request given to S7 carries the name and description only: its ``inputs`` would hand
over the answer. Both LLM conditions see ``ast.unparse`` output, so hints are the only
difference. Each LLM condition runs ``--runs`` times (default 3); nothing is executed.
"""

import argparse
import ast
import json
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict, JsonValue

from data.loaders.mcp_tools import McpTool, load_tools
from toolvalidator.config import load_settings
from toolvalidator.contracts import CapabilityRequest, ToolArtifact, ValidationRecord
from toolvalidator.llm.scads_client import LLMError, ScadsClient
from toolvalidator.llm.trace import TracingClient, trace_context, writer_for_run
from toolvalidator.sandbox.exec import NoExecutionSandbox
from toolvalidator.scoring.metrics import spearman
from toolvalidator.stages import s7_mcp_schema

CONDITIONS = ("signature", "llm_hints", "llm_stripped")
METRICS = ("valid", "precision", "recall", "f1", "type_accuracy", "required_accuracy",
           "complete", "exact", "output_ok", "output_exact")  # fmt: skip
_JSON_TYPE = {"str": "string", "int": "integer", "float": "number", "bool": "boolean",
              "list": "array", "dict": "object", "None": "null"}  # fmt: skip
RUN_ID = "rq5"


class ToolScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    valid: bool  # structurally a valid MCP Tool object
    precision: float  # input-parameter names
    recall: float
    f1: float
    type_accuracy: float | None  # on matched names; None when nothing matched
    required_accuracy: float | None
    complete: bool  # every reference parameter present
    exact: bool  # same names, types, required set and defaults (titles/descriptions ignored)
    output_ok: bool  # one string field, any name (all reference outputs are `result: string`)
    output_exact: bool  # exactly `result: string`, required


class McpRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool: str
    condition: str
    run: int
    generated: dict[str, JsonValue] | None  # the schema produced (None after an LLM error)
    error: str | None
    score: ToolScore | None
    n_params: int
    loc: int


def signature_schema(code: str, name: str) -> dict[str, JsonValue]:
    """FastMCP's own derivation, from the source: hints → types, defaults → optional."""
    fn = _function(ast.parse(code), name)
    args = fn.args.args
    defaults = dict(zip([a.arg for a in args[len(args) - len(fn.args.defaults) :]],
                        fn.args.defaults, strict=True))  # fmt: skip
    properties: dict[str, JsonValue] = {}
    for arg in args:
        prop: dict[str, JsonValue] = {"type": _json_type(arg.annotation)}
        if arg.arg in defaults:
            prop["default"] = ast.literal_eval(defaults[arg.arg])
        properties[arg.arg] = prop
    required: list[JsonValue] = [a.arg for a in args if a.arg not in defaults]
    returns = _json_type(fn.returns)
    output: dict[str, JsonValue] = {"type": "object", "properties": {"result": {"type": returns}},
                                    "required": ["result"]}  # fmt: skip
    return {
        "name": name,
        "description": ast.get_docstring(fn) or "",
        "inputSchema": {"type": "object", "properties": properties, "required": required},
        "outputSchema": output,
    }


def strip_hints(code: str) -> str:
    """The same code with every type annotation removed (``ast.unparse`` output)."""
    return ast.unparse(_StripHints().visit(ast.parse(code)))


def score_schema(schema: dict[str, JsonValue], reference: McpTool) -> ToolScore:
    gen_props, gen_req = _inputs(schema.get("inputSchema"))
    ref_props, ref_req = _inputs(reference.input_schema)
    matched = sorted(set(gen_props) & set(ref_props))
    precision = len(matched) / len(gen_props) if gen_props else float(not ref_props)
    recall = len(matched) / len(ref_props) if ref_props else float(not gen_props)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    type_ok = [gen_props[n][0] == ref_props[n][0] for n in matched]
    req_ok = [(n in gen_req) == (n in ref_req) for n in matched]
    return ToolScore(
        valid=not s7_mcp_schema.schema_problems(schema),
        precision=precision,
        recall=recall,
        f1=f1,
        type_accuracy=sum(type_ok) / len(type_ok) if type_ok else None,
        required_accuracy=sum(req_ok) / len(req_ok) if req_ok else None,
        complete=set(ref_props) <= set(gen_props),
        exact=gen_props == ref_props and gen_req == ref_req,
        output_ok=_one_string_field(schema.get("outputSchema"), name=None),
        output_exact=_one_string_field(schema.get("outputSchema"), name="result"),
    )


def signature_row(tool: McpTool) -> McpRow:
    schema = signature_schema(tool.code, tool.name)
    return McpRow(tool=tool.name, condition="signature", run=0, generated=schema, error=None,
                  score=score_schema(schema, tool), **_complexity(tool))  # fmt: skip


def evaluate_llm(tool: McpTool, condition: str, run: int, client: ScadsClient) -> McpRow:
    code = (
        strip_hints(tool.code) if condition == "llm_stripped" else ast.unparse(ast.parse(tool.code))
    )
    request = CapabilityRequest(name=tool.name, capability=tool.name, description=tool.description)
    record = ValidationRecord(request=request)
    empty = McpRow(tool=tool.name, condition=condition, run=run, generated=None, error=None,
                   score=None, **_complexity(tool))  # fmt: skip
    try:
        with trace_context(tool_id=tool.name, variant=condition, attempt=run):
            result = s7_mcp_schema.run(ToolArtifact(tool_id=tool.name, code=code), record,
                                       NoExecutionSandbox(), client=client)  # fmt: skip
    except LLMError as exc:
        return empty.model_copy(update={"error": f"{type(exc).__name__}: {exc}"[:300]})
    schema = cast(dict[str, JsonValue], result.data["schema"])
    return empty.model_copy(update={"generated": schema, "score": score_schema(schema, tool)})


def summarize(rows: Sequence[McpRow]) -> dict[str, JsonValue]:
    conditions: dict[str, JsonValue] = {}
    for condition in sorted({r.condition for r in rows}):
        mine = [r for r in rows if r.condition == condition]
        scored = [r.score for r in mine if r.score is not None]
        entry: dict[str, JsonValue] = {
            "rows": len(mine),
            "errors": sum(r.error is not None for r in mine),
        }
        for metric in METRICS:
            values = [float(v) for s in scored if (v := getattr(s, metric)) is not None]
            entry[metric] = sum(values) / len(values) if values else None
        entry["runs_identical"] = _runs_identical(mine)
        entry["f1_vs_complexity"] = _complexity_correlation(mine)
        conditions[condition] = entry
    return {"tools": len({r.tool for r in rows}), "conditions": conditions}


# --- helpers ---------------------------------------------------------------------------------


class _StripHints(ast.NodeTransformer):
    def visit_arg(self, node: ast.arg) -> ast.arg:
        node.annotation = None
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        node.returns = None
        self.generic_visit(node)
        return node

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.stmt | None:
        if node.value is None:
            return None
        return ast.copy_location(ast.Assign(targets=[node.target], value=node.value), node)


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise ValueError(f"no function {name}")


def _json_type(annotation: ast.expr | None) -> str:
    if annotation is None:
        return "string"  # FastMCP treats an unannotated parameter as Any; no hint to read
    base = annotation.value if isinstance(annotation, ast.Subscript) else annotation
    text = ast.unparse(base)
    return _JSON_TYPE.get(text.split(".")[-1], "object")


def _inputs(value: JsonValue) -> tuple[dict[str, tuple[JsonValue, JsonValue]], set[str]]:
    """name → (type, default or the 'no default' marker), and the required set."""
    if not isinstance(value, dict):
        return {}, set()
    properties = value.get("properties")
    required = value.get("required")
    props: dict[str, tuple[JsonValue, JsonValue]] = {}
    for name, spec in (properties if isinstance(properties, dict) else {}).items():
        spec = spec if isinstance(spec, dict) else {}
        kind = spec.get("type")
        kind = kind[0] if isinstance(kind, list) and len(kind) == 1 else kind
        props[name] = (kind, spec.get("default", "<no default>"))
    names = {str(r) for r in required} if isinstance(required, list) else set()
    return props, names


def _one_string_field(value: JsonValue, *, name: str | None) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get("properties"), dict):
        return False
    props = cast(dict[str, JsonValue], value["properties"])
    if len(props) != 1:
        return False
    [(field, spec)] = props.items()
    is_string = isinstance(spec, dict) and spec.get("type") == "string"
    if name is None:
        return is_string
    return is_string and field == name and value.get("required") == [name]


def _complexity(tool: McpTool) -> dict[str, int]:
    fn = _function(ast.parse(tool.code), tool.name)
    params = tool.input_schema.get("properties")
    return {"n_params": len(params) if isinstance(params, dict) else 0,
            "loc": (fn.end_lineno or fn.lineno) - fn.lineno + 1}  # fmt: skip


def _runs_identical(rows: Sequence[McpRow]) -> dict[str, JsonValue]:
    by_tool: dict[str, list[str]] = {}
    for r in rows:
        if r.generated is not None:
            props = _inputs(r.generated.get("inputSchema"))[0]
            by_tool.setdefault(r.tool, []).append(json.dumps(props, sort_keys=True))
    repeated = {t: v for t, v in by_tool.items() if len(v) > 1}
    return {
        "tools": len(repeated),
        "identical": sum(1 for v in repeated.values() if len(set(v)) == 1),
    }


def _complexity_correlation(rows: Sequence[McpRow]) -> dict[str, JsonValue]:
    per_tool: dict[str, list[float]] = {}
    size: dict[str, tuple[int, int]] = {}
    for r in rows:
        if r.score is not None:
            per_tool.setdefault(r.tool, []).append(r.score.f1)
            size[r.tool] = (r.n_params, r.loc)
    tools = sorted(per_tool)
    f1 = [sum(per_tool[t]) / len(per_tool[t]) for t in tools]
    return {"n": len(tools), "params": _rho([float(size[t][0]) for t in tools], f1),
            "loc": _rho([float(size[t][1]) for t in tools], f1)}  # fmt: skip


def _rho(a: list[float], b: list[float]) -> float | None:
    try:
        return spearman(a, b) if len(a) > 2 else None
    except ValueError:  # constant input (e.g. every tool scored 1.0): undefined, not 0
        return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_mcp_accuracy")
    parser.add_argument("--project-b", type=Path, required=True, help="Project B checkout")
    parser.add_argument("--out", type=Path, default=Path("results/rq5"))
    parser.add_argument(
        "--snapshot", type=Path, default=Path("data/mcp_tools/research_tools.jsonl")
    )
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args(argv)

    root = args.project_b
    tools = load_tools(root / "mcp_servers/research_tools/server.py",
                       *sorted(root.glob("data/live*traces*.jsonl")))  # fmt: skip
    args.snapshot.parent.mkdir(parents=True, exist_ok=True)
    args.snapshot.write_text("".join(t.model_dump_json() + "\n" for t in tools), encoding="utf-8")
    print(f"{len(tools)} tools loaded (snapshot: {args.snapshot})", flush=True)

    settings = load_settings()
    client = cast(
        ScadsClient, TracingClient(ScadsClient(settings.llm), writer_for_run(args.out, RUN_ID))
    )
    rows = [signature_row(t) for t in tools]
    with trace_context(run_id=RUN_ID):
        for run in range(args.runs):
            for condition in ("llm_hints", "llm_stripped"):
                for tool in tools:
                    rows.append(evaluate_llm(tool, condition, run, client))
                print(f"  run {run} {condition} done", flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "mcp_accuracy.jsonl").write_text(
        "".join(r.model_dump_json() + "\n" for r in rows), encoding="utf-8")  # fmt: skip
    summary = {**summarize(rows), "prompt": "generate_mcp_schema@v1", "runs": args.runs,
               "generator_model": settings.llm.generator_model}  # fmt: skip
    (args.out / "mcp_accuracy.summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
