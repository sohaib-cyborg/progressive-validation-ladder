"""Thin CLI entry point. No business logic here (CLAUDE.md §9).

    python -m toolvalidator.cli validate --tool examples/celsius.py --request examples/celsius.json

Prints the ValidationRecord as JSON. Exit code: 0 ACCEPT, 1 REJECT,
2 usage/input error, 3 NEEDS_REVIEW.

    python -m toolvalidator.cli prompts --write    # regenerate docs/PROMPTS.md
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from toolvalidator.config import load_settings
from toolvalidator.contracts import CapabilityRequest, ToolArtifact, Verdict
from toolvalidator.pipeline import run_pipeline, static_stages
from toolvalidator.prompts import markdown_catalogue
from toolvalidator.sandbox.exec import NoExecutionSandbox

PROMPTS_DOC = Path("docs/PROMPTS.md")
_EXIT_CODES = {Verdict.ACCEPT: 0, Verdict.REJECT: 1, Verdict.NEEDS_REVIEW: 3}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="toolvalidator")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="validate one tool (static-only for now)")
    validate.add_argument("--tool", type=Path, required=True, help="Python file of the tool")
    validate.add_argument("--request", type=Path, required=True, help="Capability Request JSON")
    prompts = sub.add_parser("prompts", help="print every registered prompt as Markdown")
    prompts.add_argument("--write", action="store_true", help=f"write {PROMPTS_DOC} instead")
    args = parser.parse_args(argv)

    if args.command == "prompts":
        catalogue = markdown_catalogue()
        if args.write:
            PROMPTS_DOC.write_text(catalogue, encoding="utf-8")
            print(f"wrote {PROMPTS_DOC}")
        else:
            print(catalogue, end="")
        return 0

    try:
        code = args.tool.read_text(encoding="utf-8")
        request = CapabilityRequest.model_validate_json(args.request.read_bytes())
    except (OSError, ValidationError) as exc:
        parser.error(str(exc))

    artifact = ToolArtifact(tool_id=args.tool.stem, code=code)
    # TODO(scope): only the static configuration exists until the Docker sandbox lands.
    stages = static_stages(load_settings())
    record = run_pipeline(artifact, request, stages, NoExecutionSandbox())
    print(record.model_dump_json(indent=2))
    if record.verdict is None:
        raise RuntimeError("pipeline finished without a verdict")
    return _EXIT_CODES[record.verdict]


if __name__ == "__main__":
    sys.exit(main())
