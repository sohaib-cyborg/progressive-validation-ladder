"""Provision and destroy the locked-down sandbox container (CLAUDE.md §7).

The limits are the ones verified by docker_probe.py (2026-09-17). The container
idles on ``sleep infinity`` and runs as ``nobody``. Code runs via ``sandbox/exec.py``.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from toolvalidator.config import SandboxSettings

SANDBOX_USER = "65534:65534"  # nobody:nogroup
LABELS = {"toolvalidator": "sandbox"}


def container_config(settings: SandboxSettings) -> dict[str, Any]:
    """Keyword arguments for ``client.containers.run``. No mounts, no network."""
    return {
        "image": settings.image,
        "command": ["sleep", "infinity"],
        "detach": True,
        "user": SANDBOX_USER,
        "network_disabled": True,
        "mem_limit": settings.mem_limit,
        "memswap_limit": settings.mem_limit,
        "pids_limit": settings.pids_limit,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges"],
        "labels": LABELS,
    }


# Any: the docker SDK ships no type information.
@contextmanager
def provision(client: Any, settings: SandboxSettings) -> Iterator[Any]:
    """Create a sandbox container; it is force-removed on exit, even after an error."""
    container = client.containers.run(**container_config(settings))
    try:
        yield container
    finally:
        container.remove(force=True)
