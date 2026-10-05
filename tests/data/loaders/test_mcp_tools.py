"""Tests for the MCP tool loader (data/loaders/mcp_tools.py)."""

import ast
import json
from pathlib import Path

import pytest

from data.loaders.mcp_tools import McpTool, load_tools

SERVER = '''"""A toy server."""

from __future__ import annotations

import json
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("toy")

RATES = {"EUR": 1.0}
UNUSED = 3


def _rate(code: str) -> float:
    return RATES[code]


def _unused() -> None:
    pass


@mcp.tool()
def convert(amount: float, currency: str = "EUR") -> str:
    """Converts an amount."""
    return json.dumps(amount * _rate(currency))


@mcp.tool()
def ping() -> str:
    """Says pong."""
    return "pong"


if __name__ == "__main__":
    mcp.run()
'''

SCHEMAS = {
    "convert": {
        "name": "convert",
        "description": "Converts an amount.",
        "inputSchema": {"type": "object", "title": "convertArguments",
                        "properties": {"amount": {"title": "Amount", "type": "number"},
                                       "currency": {"title": "Currency", "type": "string",
                                                    "default": "EUR"}},
                        "required": ["amount"]},
        "outputSchema": {"type": "object", "properties": {"result": {"type": "string"}},
                         "required": ["result"]},
    },
    "ping": {
        "name": "ping",
        "description": "Says pong.",
        "inputSchema": {"type": "object", "properties": {}, "title": "pingArguments"},
        "outputSchema": {"type": "object", "properties": {"result": {"type": "string"}},
                         "required": ["result"]},
    },
}  # fmt: skip


def _write(tmp_path: Path, schemas: dict[str, object] = SCHEMAS) -> tuple[Path, Path]:
    server = tmp_path / "server.py"
    server.write_text(SERVER, encoding="utf-8")
    traces = tmp_path / "traces.jsonl"
    traces.write_text(
        json.dumps({"trace_id": "t1", "tool_schemas": schemas}) + "\n", encoding="utf-8"
    )
    return server, traces


def test_every_decorated_function_becomes_a_tool_with_its_real_schema(tmp_path: Path) -> None:
    tools = load_tools(*_write(tmp_path))
    assert [t.name for t in tools] == ["convert", "ping"]
    convert = tools[0]
    assert convert.description == "Converts an amount."
    assert convert.input_schema == SCHEMAS["convert"]["inputSchema"]  # type: ignore[index]
    assert convert.output_schema["required"] == ["result"]


def test_code_is_standalone_with_only_the_helpers_it_uses(tmp_path: Path) -> None:
    convert = load_tools(*_write(tmp_path))[0]
    tree = ast.parse(convert.code)  # parses on its own
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert names == {"_rate", "convert"}  # _unused is left out
    assert "RATES = " in convert.code and "UNUSED" not in convert.code
    assert "mcp" not in convert.code  # no FastMCP import, object or decorator
    assert "import json" in convert.code


def test_a_tool_without_a_recorded_schema_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ping"):
        load_tools(*_write(tmp_path, {"convert": SCHEMAS["convert"]}))


def test_conflicting_recorded_schemas_are_an_error(tmp_path: Path) -> None:
    server, traces = _write(tmp_path)
    other = json.loads(json.dumps(SCHEMAS))
    other["ping"]["description"] = "Changed."
    with traces.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"trace_id": "t2", "tool_schemas": other}) + "\n")
    with pytest.raises(ValueError, match="ping"):
        load_tools(server, traces)


def test_tools_round_trip_as_json(tmp_path: Path) -> None:
    tool = load_tools(*_write(tmp_path))[1]
    assert McpTool.model_validate_json(tool.model_dump_json()) == tool
