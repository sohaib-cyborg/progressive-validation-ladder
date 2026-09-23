"""Shared fixtures.

The fake sandbox never executes code (CLAUDE.md §7). The real-Docker fixtures skip,
with a reason, when the daemon is down or the sandbox image is not built.
"""

from collections.abc import Iterator
from typing import Any

import pytest

from toolvalidator.contracts import CapabilityRequest, ExecResult, ParamSpec, ValidationRecord


class FakeSandbox:
    """Records every ``run`` call and returns a canned result. Executes nothing."""

    def __init__(self, result: ExecResult | None = None) -> None:
        self.result = result or ExecResult(stdout="", stderr="", exit_code=0, duration_s=0.0)
        self.calls: list[tuple[str, str, float | None]] = []

    def run(self, script: str, *, stdin: str = "", timeout_s: float | None = None) -> ExecResult:
        self.calls.append((script, stdin, timeout_s))
        return self.result


@pytest.fixture
def fake_sandbox() -> FakeSandbox:
    return FakeSandbox()


@pytest.fixture
def record() -> ValidationRecord:
    return ValidationRecord(
        request=CapabilityRequest(
            name="celsius_to_fahrenheit",
            capability="celsius_to_fahrenheit",
            description="Convert a temperature in Celsius to Fahrenheit.",
            inputs=[ParamSpec(name="stdin", type="string", description="Degrees Celsius")],
            outputs=[ParamSpec(name="stdout", type="string", description="Degrees Fahrenheit")],
        )
    )


@pytest.fixture(scope="session")
def docker_client() -> Iterator[Any]:  # Any: the docker SDK ships no type information
    import docker

    try:
        client = docker.from_env(timeout=120)
        client.ping()
    except Exception as exc:  # any failure to reach the daemon means "skip", not "fail"
        pytest.skip(f"Docker daemon not reachable: {exc}")
    yield client
    client.close()


@pytest.fixture(scope="session")
def sandbox_image(docker_client: Any) -> str:
    """The configured sandbox image; skips (with the build command) if it isn't built."""
    import docker.errors

    from toolvalidator.config import SandboxSettings

    image = SandboxSettings().image
    try:
        docker_client.images.get(image)
    except docker.errors.ImageNotFound:
        pytest.skip(f"{image} not built: docker build -t {image} toolvalidator/sandbox")
    return image
