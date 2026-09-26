"""Tests for the prompt registry (toolvalidator/prompts/)."""

from pathlib import Path

import pytest

from toolvalidator.contracts import CapabilityRequest, IOExample, ParamSpec
from toolvalidator.prompts import REGISTRY, PromptSpec, markdown_catalogue, spec
from toolvalidator.testgen.schemas import GeneratedTest

REQUEST = CapabilityRequest(
    name="add_two",
    capability="add_two",
    description="Read two integers and print their sum.",
    inputs=[ParamSpec(name="stdin", type="string", description="Two integers")],
    outputs=[ParamSpec(name="stdout", type="string", description="Their sum")],
    rationale="No available tool adds numbers.",
)
DOC = Path(__file__).resolve().parents[2] / "docs" / "PROMPTS.md"


def test_registry_is_not_empty_and_keys_are_unique() -> None:
    assert REGISTRY
    keys = [(s.id, s.version) for s in REGISTRY.values()]
    assert len(keys) == len(set(keys))
    for (key_id, key_version), value in REGISTRY.items():
        assert (key_id, key_version) == (value.id, value.version)


def test_every_spec_has_documentation_fields_and_a_system_prompt() -> None:
    for value in REGISTRY.values():
        assert value.system.strip(), value.id
        assert value.purpose.strip(), value.id
        assert value.changelog.strip(), value.id
        assert value.role in ("generator", "judge"), value.id


def test_lookup_by_id_and_version() -> None:
    generate = spec("generate_tests", "v1")
    assert isinstance(generate, PromptSpec)
    assert generate.role == "generator"
    with pytest.raises(KeyError, match="no_such_prompt"):
        spec("no_such_prompt", "v1")


def test_generate_prompt_renders_the_request() -> None:
    rendered = spec("generate_tests", "v1").render(
        request=REQUEST, code="print(1)", n=3, examples=[IOExample(input="2 3", output="5")]
    )
    assert "Capability: add_two" in rendered
    assert "Write 3 test cases" in rendered
    assert "print(1)" in rendered


def test_judge_prompt_renders_one_case_and_never_the_code() -> None:
    rendered = spec("judge_test", "v1").render(
        request=REQUEST, test=GeneratedTest(input="2 3", output="5")
    )
    assert "expected output" in rendered
    assert "Program source" not in rendered


def test_explain_prompt_shows_the_code_and_never_the_description() -> None:
    explain = spec("explain_code", "v1")
    assert explain.role == "generator"
    rendered = explain.render(code="print(sum(map(int, input().split())))")
    assert "print(sum(map(int" in rendered
    assert REQUEST.description not in rendered


def test_compare_prompt_shows_description_and_explanation_never_the_code() -> None:
    compare = spec("compare_explanation", "v1")
    assert compare.role == "judge"
    rendered = compare.render(request=REQUEST, explanation="It prints the product of two ints.")
    assert REQUEST.description in rendered
    assert "It prints the product of two ints." in rendered
    assert "stdout: string" in rendered  # declared outputs are part of the spec
    assert "Program source" not in rendered and "```python" not in rendered


def test_markdown_catalogue_quotes_every_registered_prompt() -> None:
    text = markdown_catalogue()
    for value in REGISTRY.values():
        assert f"{value.id}@{value.version}" in text
        assert value.system.splitlines()[0] in text


def test_docs_prompts_md_is_in_sync_with_the_registry() -> None:
    # Regenerate with: python -m toolvalidator.cli prompts --write
    assert DOC.exists(), "docs/PROMPTS.md is missing; run the CLI to generate it"
    assert DOC.read_text(encoding="utf-8") == markdown_catalogue()


def test_judge_batch_prompt_numbers_every_case_and_never_shows_code() -> None:
    judge = spec("judge_batch", "v1")
    assert judge.role == "judge"
    rendered = judge.render(
        request=REQUEST,
        tests=[GeneratedTest(input="2 3", output="5"), GeneratedTest(input="1 1", output="2")],
    )
    assert "Test 0" in rendered and "Test 1" in rendered
    assert REQUEST.description in rendered
    assert "Program source" not in rendered and "```python" not in rendered
