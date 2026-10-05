"""S7 MCP schema: propose the tool's MCP definition (input and output JSON Schema).

One generator call (``generate_mcp_schema@v1``) sees the request and the code and returns
an MCP Tool object. The structure is then checked in plain Python (``schema_problems``):
an object ``inputSchema`` with typed properties, ``required`` naming only real properties,
and the same for ``outputSchema`` when present. S7 always passes — an LLM never decides
a verdict — and records the schema and any problems. A reply with no JSON object raises
``LLMOutputError`` (an infrastructure failure, not a verdict). Nothing is executed.
"""

from pydantic import JsonValue

from toolvalidator.contracts import Sandbox, StageResult, ToolArtifact, ValidationRecord
from toolvalidator.llm.scads_client import ScadsClient, parse_json_object
from toolvalidator.llm.trace import trace_context
from toolvalidator.prompts.mcp import GENERATE_MCP_SCHEMA_V1

STAGE = "s7_mcp_schema"
PROMPT = GENERATE_MCP_SCHEMA_V1
JSON_TYPES = frozenset({"string", "integer", "number", "boolean", "array", "object", "null"})


def run(
    artifact: ToolArtifact, record: ValidationRecord, sandbox: Sandbox, *, client: ScadsClient
) -> StageResult:
    with trace_context(prompt_id=PROMPT.id, prompt_version=PROMPT.version):
        result = client.complete(
            PROMPT.role, system=PROMPT.system,
            user=PROMPT.render(request=record.request, code=artifact.code),
        )  # fmt: skip
    schema = parse_json_object(result.content)
    problems = schema_problems(schema)
    data: dict[str, JsonValue] = {
        "schema": schema,
        "valid": not problems,
        "problems": list(problems),
        "prompt": f"{PROMPT.id}@{PROMPT.version}",
    }
    category = None if not problems else "invalid_schema"
    detail = "valid MCP tool schema" if not problems else "; ".join(problems)[:300]
    return record.add(
        StageResult(stage=STAGE, passed=True, category=category, detail=detail, data=data)
    )


def schema_problems(schema: dict[str, JsonValue]) -> list[str]:
    """Structural problems of an MCP Tool object; empty when it is well formed."""
    problems: list[str] = []
    if not isinstance(schema.get("name"), str) or not schema.get("name"):
        problems.append("name: missing or not a string")
    if "inputSchema" not in schema:
        problems.append("inputSchema: missing")
    else:
        problems += _object_problems("inputSchema", schema["inputSchema"])
    if "outputSchema" in schema and schema["outputSchema"] is not None:
        problems += _object_problems("outputSchema", schema["outputSchema"])
    return problems


def _object_problems(where: str, value: JsonValue) -> list[str]:
    if not isinstance(value, dict) or value.get("type") != "object":
        return [f"{where}: type must be object"]
    properties = value.get("properties", {})
    if not isinstance(properties, dict):
        return [f"{where}: properties must be an object"]
    problems = [
        f"{where}.{name}: no valid JSON type"
        for name, spec in properties.items()
        if not (isinstance(spec, dict) and _valid_type(spec.get("type")))
    ]
    required = value.get("required", [])
    if not isinstance(required, list) or any(r not in properties for r in required):
        problems.append(f"{where}: required names a missing property")
    return problems


def _valid_type(value: JsonValue) -> bool:
    if isinstance(value, str):
        return value in JSON_TYPES
    return isinstance(value, list) and bool(value) and all(v in JSON_TYPES for v in value)
