"""Tests for sandbox execution (toolvalidator/sandbox/exec.py)."""

import io
import json
import tarfile
from collections.abc import Iterator
from typing import Any

import pytest

from toolvalidator.config import SandboxSettings
from toolvalidator.contracts import ExecResult, Sandbox
from toolvalidator.sandbox.container import provision
from toolvalidator.sandbox.exec import (
    DockerSandbox,
    ExecutionNotAllowedError,
    NoExecutionSandbox,
    SandboxError,
    build_archive,
    parse_runner_output,
)

# --- NoExecutionSandbox ----------------------------------------------------------


def test_no_execution_sandbox_is_a_sandbox() -> None:
    assert isinstance(NoExecutionSandbox(), Sandbox)


def test_no_execution_sandbox_refuses_to_run() -> None:
    with pytest.raises(ExecutionNotAllowedError):
        NoExecutionSandbox().run("print('hi')", stdin="", timeout_s=1.0)


# --- unit: archive + runner output -----------------------------------------------


def test_build_archive_owned_by_nobody() -> None:
    data = build_archive("tv-run-7", {"script.py": b"print(1)", "stdin.txt": b"x"})
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        members = {m.name: m for m in tar.getmembers()}
        assert set(members) == {"tv-run-7", "tv-run-7/script.py", "tv-run-7/stdin.txt"}
        assert members["tv-run-7"].isdir()
        assert all(m.uid == m.gid == 65534 for m in members.values())
        script = tar.extractfile(members["tv-run-7/script.py"])
        assert script is not None and script.read() == b"print(1)"


def test_parse_runner_output_ok() -> None:
    payload = {"stdout": "2\n", "stderr": "", "exit_code": 0, "timed_out": False, "duration_s": 0.1}
    assert parse_runner_output(0, json.dumps(payload).encode(), b"") == ExecResult(**payload)


def test_parse_runner_output_runner_failure_is_sandbox_error() -> None:
    with pytest.raises(SandboxError, match="boom"):
        parse_runner_output(1, b"", b"boom")


def test_parse_runner_output_malformed_is_sandbox_error() -> None:
    with pytest.raises(SandboxError):
        parse_runner_output(0, b"not json", b"")


class _FakeContainer:
    def __init__(self) -> None:
        self.cmds: list[list[str]] = []

    def put_archive(self, path: str, data: bytes) -> bool:
        return True

    def exec_run(self, cmd: list[str], demux: bool) -> tuple[int, tuple[bytes, bytes]]:
        self.cmds.append(cmd)
        out = {"stdout": "", "stderr": "", "exit_code": 0, "timed_out": False, "duration_s": 0.0}
        return 0, (json.dumps(out).encode(), b"")


def test_docker_sandbox_defaults_timeout_and_uses_fresh_run_dirs() -> None:
    container = _FakeContainer()
    sandbox = DockerSandbox(container, SandboxSettings(timeout_s=7.0, max_output_bytes=99))
    assert isinstance(sandbox, Sandbox)
    sandbox.run("print(1)")
    sandbox.run("print(2)", timeout_s=1.5)
    (first, second) = container.cmds
    assert first[2:] == [first[2], "7.0", "99"] and second[3] == "1.5"
    assert first[2] != second[2]  # a new directory per run


def test_docker_sandbox_failed_upload_is_sandbox_error() -> None:
    container = _FakeContainer()
    container.put_archive = lambda path, data: False  # type: ignore[method-assign]
    with pytest.raises(SandboxError, match="upload"):
        DockerSandbox(container, SandboxSettings()).run("print(1)")


# --- real Docker -----------------------------------------------------------------


@pytest.fixture(scope="module")
def sandbox(docker_client: Any, sandbox_image: str) -> Iterator[DockerSandbox]:
    settings = SandboxSettings(max_output_bytes=64 * 1024)
    with provision(docker_client, settings) as container:
        yield DockerSandbox(container, settings)


@pytest.mark.slow
def test_real_stdin_stdout_stderr(sandbox: DockerSandbox) -> None:
    res = sandbox.run(
        "import sys\nprint(int(input()) + 1)\nprint('e', file=sys.stderr)", stdin="41\n"
    )
    assert (res.stdout, res.stderr, res.exit_code, res.timed_out) == ("42\n", "e\n", 0, False)


@pytest.mark.slow
def test_real_exit_code(sandbox: DockerSandbox) -> None:
    assert sandbox.run("raise SystemExit(3)").exit_code == 3


@pytest.mark.slow
def test_real_timeout_kills_runaway(sandbox: DockerSandbox) -> None:
    res = sandbox.run("while True: pass", timeout_s=1.0)
    assert res.timed_out
    assert res.exit_code == 137  # SIGKILL
    assert res.duration_s < 5


@pytest.mark.slow
def test_real_network_is_blocked(sandbox: DockerSandbox) -> None:
    script = "import urllib.request\nurllib.request.urlopen('http://example.com', timeout=3)"
    res = sandbox.run(script)
    assert res.exit_code != 0


@pytest.mark.slow
def test_real_runs_as_nobody(sandbox: DockerSandbox) -> None:
    assert sandbox.run("import os\nprint(os.getuid(), os.getgid())").stdout == "65534 65534\n"


@pytest.mark.slow
def test_real_output_is_capped(sandbox: DockerSandbox) -> None:
    res = sandbox.run("while True: print('x' * 1000)")
    assert len(res.stdout) == 64 * 1024
    assert res.exit_code != 0  # writing past the cap fails ("File too large")


@pytest.mark.slow
def test_real_large_stdin(sandbox: DockerSandbox) -> None:
    res = sandbox.run("import sys\nprint(len(sys.stdin.read()))", stdin="a" * 1_400_000)
    assert res.stdout == "1400000\n"


@pytest.mark.slow
def test_real_sandbox_image_has_numpy(sandbox: DockerSandbox) -> None:
    # 1.6% of RunBugRun Python entries import numpy (DECISIONS.md).
    res = sandbox.run("import numpy; print(numpy.__version__)")
    assert (res.exit_code, res.stdout.strip()) == (0, "1.26.4")
