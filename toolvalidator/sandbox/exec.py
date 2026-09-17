"""Sandbox execution: the only place tool code may run (CLAUDE.md §7).

``DockerSandbox`` uploads the script, its stdin and a small trusted runner into a
container from ``sandbox/container.py``, then executes the runner there. The runner
enforces the timeout (kills the whole process group) and caps output size with
RLIMIT_FSIZE, then reports the result as JSON. Design was verified on real Docker
first (docs/reports/sprint-01.md).
"""

import io
import itertools
import tarfile
from collections.abc import Mapping
from typing import Any

from docker.errors import DockerException
from pydantic import ValidationError

from toolvalidator.config import SandboxSettings
from toolvalidator.contracts import ExecResult

SANDBOX_UID = 65534  # nobody, matches container.SANDBOX_USER
_WORK_ROOT = "/tmp"

_RUNNER = r"""
import json, os, resource, signal, subprocess, sys, time

run_dir, timeout, cap = sys.argv[1], float(sys.argv[2]), int(sys.argv[3])


def limit_output():
    resource.setrlimit(resource.RLIMIT_FSIZE, (cap, cap))


def read(name):
    with open(os.path.join(run_dir, name), "rb") as f:
        return f.read(cap).decode("utf-8", "replace")


def path(name):
    return os.path.join(run_dir, name)


start = time.monotonic()
with (
    open(path("stdin.txt"), "rb") as fin,
    open(path("out"), "wb") as fout,
    open(path("err"), "wb") as ferr,
):
    proc = subprocess.Popen(
        [sys.executable, "script.py"], stdin=fin, stdout=fout, stderr=ferr, cwd=run_dir,
        preexec_fn=limit_output, start_new_session=True,
    )
    try:
        proc.wait(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        timed_out = True
    try:
        os.killpg(proc.pid, signal.SIGKILL)  # also reaps anything the tool spawned
    except ProcessLookupError:
        pass
    proc.wait()
duration = time.monotonic() - start
code = proc.returncode if proc.returncode >= 0 else 128 - proc.returncode
print(json.dumps({"stdout": read("out"), "stderr": read("err"), "exit_code": code,
                  "timed_out": timed_out, "duration_s": duration}))
"""


class ExecutionNotAllowedError(RuntimeError):
    """A stage tried to execute code in a configuration that forbids execution."""


class SandboxError(RuntimeError):
    """The sandbox itself failed (upload, runner, Docker API): not a verdict on the tool."""


class NoExecutionSandbox:
    """Sandbox for static-only configurations: any attempt to run code is an error."""

    def run(self, script: str, *, stdin: str = "", timeout_s: float | None = None) -> ExecResult:
        raise ExecutionNotAllowedError("this configuration does not execute tool code")


class DockerSandbox:
    """Runs scripts inside a provisioned container.

    The docker client that created ``container`` must have an HTTP timeout longer
    than any ``timeout_s`` used here.
    """

    # Any: the docker SDK ships no type information.
    def __init__(self, container: Any, settings: SandboxSettings) -> None:
        self._container = container
        self._settings = settings
        self._runs = itertools.count()

    def run(self, script: str, *, stdin: str = "", timeout_s: float | None = None) -> ExecResult:
        timeout = self._settings.timeout_s if timeout_s is None else timeout_s
        run_name = f"tv-run-{next(self._runs)}"
        run_dir = f"{_WORK_ROOT}/{run_name}"
        files = {
            "runner.py": _RUNNER.encode(),
            "script.py": script.encode(),
            "stdin.txt": stdin.encode(),
        }
        cmd = [
            "python",
            f"{run_dir}/runner.py",
            run_dir,
            str(timeout),
            str(self._settings.max_output_bytes),
        ]
        try:
            if not self._container.put_archive(_WORK_ROOT, build_archive(run_name, files)):
                raise SandboxError("upload to sandbox failed")
            exit_code, (stdout, stderr) = self._container.exec_run(cmd, demux=True)
        except (DockerException, OSError) as exc:
            raise SandboxError(f"docker API error: {exc}") from exc
        return parse_runner_output(exit_code, stdout or b"", stderr or b"")


def build_archive(run_name: str, files: Mapping[str, bytes]) -> bytes:
    """A tar with ``run_name/`` and ``files``, owned by the sandbox user."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        tar.addfile(_tar_info(run_name, tarfile.DIRTYPE, 0o755, 0))
        for name, data in files.items():
            tar.addfile(
                _tar_info(f"{run_name}/{name}", tarfile.REGTYPE, 0o644, len(data)), io.BytesIO(data)
            )
    return buf.getvalue()


def parse_runner_output(exit_code: int, stdout: bytes, stderr: bytes) -> ExecResult:
    if exit_code != 0:
        detail = stderr.decode("utf-8", "replace")[-500:]
        raise SandboxError(f"sandbox runner exited {exit_code}: {detail}")
    try:
        return ExecResult.model_validate_json(stdout)
    except ValidationError as exc:
        raise SandboxError(f"unreadable runner output: {stdout[:200]!r}") from exc


def _tar_info(name: str, kind: bytes, mode: int, size: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type, info.mode, info.size = kind, mode, size
    info.uid = info.gid = SANDBOX_UID
    return info
