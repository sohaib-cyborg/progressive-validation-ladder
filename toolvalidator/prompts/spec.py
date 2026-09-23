"""The prompt type and the documentation renderer (no prompts live here)."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from toolvalidator.llm.scads_client import Role


@dataclass(frozen=True)
class PromptSpec:
    """One prompt: its system text, its renderer, and what it is for."""

    id: str
    version: str
    role: Role
    purpose: str
    changelog: str
    system: str
    renderer: Callable[..., str]

    @property
    def key(self) -> tuple[str, str]:
        return (self.id, self.version)

    def render(self, **params: Any) -> str:
        """Build the user message. Keyword-only, so call sites stay readable."""
        return self.renderer(**params)


def register(*specs: PromptSpec) -> dict[tuple[str, str], PromptSpec]:
    registry: dict[tuple[str, str], PromptSpec] = {}
    for item in specs:
        if item.key in registry:
            raise ValueError(f"duplicate prompt {item.id}@{item.version}")
        registry[item.key] = item
    return registry


def render_catalogue(registry: Mapping[tuple[str, str], PromptSpec]) -> str:
    """The prompt appendix for docs/PROMPTS.md, generated from a registry."""
    lines = [
        "# Prompts",
        "",
        "**Generated from the registry** (`toolvalidator/prompts/`) by",
        "`python -m toolvalidator.cli prompts --write`. Do not edit by hand: a test fails if",
        "this file and the code disagree, so what you read here is what actually runs.",
        "",
        "A prompt version is immutable once a result has been produced with it. A change means",
        "a new version beside the old one, which is what makes a prompt ablation honest.",
        "",
        "Which model a role maps to, and every other LLM setting, is in `docs/LLM.md`.",
        "",
        "| Prompt | Role | Purpose |",
        "|---|---|---|",
    ]
    ordered = sorted(registry.values(), key=lambda item: item.key)
    lines += [f"| `{item.id}@{item.version}` | {item.role} | {item.purpose} |" for item in ordered]
    for item in ordered:
        lines += [
            "",
            "---",
            "",
            f"## `{item.id}@{item.version}`",
            "",
            f"- **Role:** {item.role}",
            f"- **Purpose:** {item.purpose}",
            f"- **This version:** {item.changelog}",
            "",
            "### System prompt",
            "",
            "```text",
            item.system,
            "```",
        ]
    return "\n".join(lines) + "\n"
