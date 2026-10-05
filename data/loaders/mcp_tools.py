"""Real MCP tools with their real schemas, for RQ5 (MCP schema accuracy).

Source: Project B's FastMCP server (``mcp_servers/research_tools/server.py``) and the
schemas that server sent over MCP, as recorded in Project B's trace files
(``data/live*traces*.jsonl`` → ``tool_schemas``). The server file is only **read** with
``ast``: it is never imported or run, so no ``mcp`` dependency and no tool code executes.

Each tool's code is made standalone: the module's imports (minus ``mcp``), the
module-level helpers and constants the function uses (transitively), then the function
without its ``@mcp.tool()`` decorator. Project B has no licence file, so the output is
written only to the git-ignored ``data/mcp_tools/``.
"""

import ast
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, JsonValue

__all__ = ["McpTool", "load_tools"]


class McpTool(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str  # the MCP description the server sent
    code: str  # standalone source: imports, used helpers, the function
    input_schema: dict[str, JsonValue]
    output_schema: dict[str, JsonValue]


def load_tools(server: Path, *traces: Path) -> list[McpTool]:
    """Every ``@mcp.tool()`` function in ``server`` with its recorded schema."""
    source = server.read_text(encoding="utf-8")
    tree = ast.parse(source)
    schemas = _recorded_schemas(traces)
    tools: list[McpTool] = []
    for node in tree.body:
        if not (isinstance(node, ast.FunctionDef) and _is_tool(node)):
            continue
        schema = schemas.get(node.name)
        if schema is None:
            raise ValueError(f"no recorded schema for tool {node.name}")
        tools.append(
            McpTool(
                name=node.name,
                description=str(schema.get("description") or ""),
                code=_standalone(source, tree, node),
                input_schema=_object(schema.get("inputSchema")),
                output_schema=_object(schema.get("outputSchema")),
            )
        )
    return tools


def _recorded_schemas(traces: tuple[Path, ...]) -> dict[str, dict[str, JsonValue]]:
    found: dict[str, dict[str, JsonValue]] = {}
    for path in traces:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            for name, schema in (json.loads(line).get("tool_schemas") or {}).items():
                kept = {k: schema.get(k) for k in ("description", "inputSchema", "outputSchema")}
                if name in found and found[name] != kept:
                    raise ValueError(f"tool {name} has conflicting recorded schemas")
                found[name] = kept
    return found


def _object(value: JsonValue) -> dict[str, JsonValue]:
    return value if isinstance(value, dict) else {}


def _is_tool(node: ast.FunctionDef) -> bool:
    return any(
        isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "tool"
        for d in node.decorator_list
    )


def _standalone(source: str, tree: ast.Module, tool: ast.FunctionDef) -> str:
    imports = [
        n for n in tree.body
        if isinstance(n, ast.Import | ast.ImportFrom) and not _imports_mcp(n)
    ]  # fmt: skip
    helpers = {
        name: n
        for n in tree.body
        if not (isinstance(n, ast.FunctionDef) and _is_tool(n))
        for name in _defined_names(n)
        if name != "mcp"
    }
    needed: set[str] = set()
    pending = _used_names(tool)
    while pending:
        name = pending.pop()
        if name in helpers and name not in needed:
            needed.add(name)
            pending |= _used_names(helpers[name])
    used = {id(helpers[name]) for name in needed}
    header = "\n".join(_segment(source, n) for n in imports)
    body = [_segment(source, n) for n in tree.body if id(n) in used]  # in source order
    return header + "\n\n\n" + "\n\n\n".join([*body, _segment(source, tool)]) + "\n"


def _imports_mcp(node: ast.Import | ast.ImportFrom) -> bool:
    if isinstance(node, ast.ImportFrom):
        return (node.module or "").split(".")[0] == "mcp"
    return any(alias.name.split(".")[0] == "mcp" for alias in node.names)


def _defined_names(node: ast.stmt) -> list[str]:
    if isinstance(node, ast.FunctionDef | ast.ClassDef):
        return [node.name]
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def _used_names(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _segment(source: str, node: ast.stmt) -> str:
    """The statement's source; for a function, from ``def`` on (decorators left out)."""
    text = ast.get_source_segment(source, node)
    if text is None:  # pragma: no cover - only for nodes without positions
        raise ValueError(f"no source for line {node.lineno}")
    return text
