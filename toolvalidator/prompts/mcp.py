"""The MCP schema prompt (S7, RQ5): write the MCP tool definition for a tool.

The generator sees the request and the code. It proposes the schema; S7 only records it
and checks its structure in Python, and RQ5 scores it against the real server's schema.
"""

from toolvalidator.contracts import CapabilityRequest
from toolvalidator.prompts.spec import PromptSpec
from toolvalidator.prompts.testgen import describe_param

GENERATE_MCP_SYSTEM = """You write the MCP (Model Context Protocol) tool definition for a
Python tool.

You are given the tool's request (what it should do) and its source code. The tool is the
function whose name is the tool name; an MCP client calls it with keyword arguments.
Write the MCP Tool object:
- "name": the tool name.
- "description": one sentence saying what the tool does.
- "inputSchema": a JSON Schema object ("type": "object") whose "properties" are the
  function's parameters. Give each one a JSON type: "string", "integer", "number",
  "boolean", "array", "object" or "null". A parameter with a default value is optional:
  leave it out of "required" and give its "default". List every other parameter in
  "required".
- "outputSchema": a JSON Schema object ("type": "object") describing the structured
  result the tool returns.
Describe the code as it is; do not add parameters it does not have.

Answer with JSON only:
{"name": "...", "description": "...", "inputSchema": {...}, "outputSchema": {...}}"""


def render_generate_mcp(request: CapabilityRequest, code: str) -> str:
    parts = [
        f"Tool name: {request.name}",
        f"Capability: {request.capability}",
        "",
        "What the tool does:",
        request.description.strip(),
    ]
    if request.inputs:
        parts += ["", "Declared inputs:", *(f"- {describe_param(p)}" for p in request.inputs)]
    if request.outputs:
        parts += ["", "Declared outputs:", *(f"- {describe_param(p)}" for p in request.outputs)]
    parts += [
        "",
        "Source code:",
        "```python",
        code.strip(),
        "```",
        "",
        "Write the MCP tool definition. Answer with JSON.",
    ]
    return "\n".join(parts)


GENERATE_MCP_SCHEMA_V1 = PromptSpec(
    id="generate_mcp_schema",
    version="v1",
    role="generator",
    purpose="Write the MCP tool definition (input and output JSON Schema) from request + code.",
    changelog="First version: request + code; JSON Schema types; defaults are optional.",
    system=GENERATE_MCP_SYSTEM,
    renderer=render_generate_mcp,
)
