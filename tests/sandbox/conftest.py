"""Real-Docker fixtures. Tests using them are skipped, with a reason, if the daemon is down."""

from collections.abc import Iterator
from typing import Any

import pytest


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
