"""Tests for sandbox execution (toolvalidator/sandbox/exec.py)."""

import pytest

from toolvalidator.contracts import Sandbox
from toolvalidator.sandbox.exec import ExecutionNotAllowedError, NoExecutionSandbox


def test_no_execution_sandbox_is_a_sandbox() -> None:
    assert isinstance(NoExecutionSandbox(), Sandbox)


def test_no_execution_sandbox_refuses_to_run() -> None:
    with pytest.raises(ExecutionNotAllowedError):
        NoExecutionSandbox().run("print('hi')", stdin="", timeout_s=1.0)
