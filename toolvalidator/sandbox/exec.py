"""Sandbox execution: the only place tool code may run (CLAUDE.md §7).

For now this holds only the sandbox for static-only runs, which refuses to
execute anything. The Docker-backed sandbox (task 1.6) is added here once
docker_probe.py has passed.
"""

from toolvalidator.contracts import ExecResult


class ExecutionNotAllowedError(RuntimeError):
    """A stage tried to execute code in a configuration that forbids execution."""


class NoExecutionSandbox:
    """Sandbox for static-only configurations: any attempt to run code is an error."""

    def run(self, script: str, *, stdin: str = "", timeout_s: float | None = None) -> ExecResult:
        raise ExecutionNotAllowedError("this configuration does not execute tool code")
