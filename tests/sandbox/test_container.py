"""Tests for sandbox provisioning (toolvalidator/sandbox/container.py)."""

from typing import Any

import pytest

from toolvalidator.config import SandboxSettings
from toolvalidator.sandbox.container import LABELS, SANDBOX_USER, container_config, provision


def test_config_is_locked_down() -> None:
    cfg = container_config(SandboxSettings(image="img:1", mem_limit="256m", pids_limit=64))
    assert cfg["image"] == "img:1"
    assert cfg["network_disabled"] is True
    assert cfg["cap_drop"] == ["ALL"]
    assert cfg["security_opt"] == ["no-new-privileges"]
    assert cfg["mem_limit"] == cfg["memswap_limit"] == "256m"  # no swap escape
    assert cfg["pids_limit"] == 64
    assert cfg["user"] == SANDBOX_USER == "65534:65534"
    assert cfg["labels"] == LABELS
    assert cfg["detach"] is True
    assert "volumes" not in cfg and "mounts" not in cfg and "privileged" not in cfg


class _FakeContainer:
    def __init__(self) -> None:
        self.removed_with: dict[str, Any] | None = None

    def remove(self, **kwargs: Any) -> None:
        self.removed_with = kwargs


class _FakeClient:
    def __init__(self) -> None:
        self.container = _FakeContainer()
        self.run_kwargs: dict[str, Any] = {}
        self.containers = self

    def run(self, **kwargs: Any) -> _FakeContainer:
        self.run_kwargs = kwargs
        return self.container


def test_provision_uses_config_and_always_removes() -> None:
    client = _FakeClient()
    settings = SandboxSettings()
    with pytest.raises(RuntimeError), provision(client, settings) as container:
        assert container is client.container
        raise RuntimeError("stage blew up")
    assert client.run_kwargs == container_config(settings)
    assert client.container.removed_with == {"force": True}


@pytest.mark.slow
def test_real_container_is_created_and_destroyed(docker_client: Any, sandbox_image: str) -> None:
    with provision(docker_client, SandboxSettings()) as container:
        container.reload()
        assert container.status == "running"
        attrs = container.attrs["HostConfig"]
        assert attrs["CapDrop"] == ["ALL"]
        assert attrs["PidsLimit"] == 128
        cid = container.id
    remaining = docker_client.containers.list(all=True, filters={"id": cid})
    assert remaining == []
