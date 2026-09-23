"""Comparison rules and the in-sandbox harness text used by S4.

Split out of ``s4_execute`` to keep both files under the size limit (CLAUDE.md §2).
The harness injects the very functions tested here, so the rule has one definition.
"""

import inspect
import math

from toolvalidator.stages.compare import values_match

STDIN_HARNESS_IMPORTS = "import json, math, resource, subprocess, sys"


def normalize_output(text: str) -> str:
    """Trailing whitespace is not significant; everything else is."""
    return "\n".join(line.rstrip() for line in text.rstrip().splitlines())


def outputs_match(actual: str, expected: str, *, rel_tol: float, abs_tol: float) -> bool:
    """Equal after normalisation, or equal token by token with float tolerance.

    Competitive-programming expected outputs are rounded (``12.5663706144``) while
    Python prints full precision (``12.566370614359172``). Comparing text alone
    rejects correct programs, which measured 3 of 9 false rejections in the pilot.
    """
    actual, expected = normalize_output(actual), normalize_output(expected)
    if actual == expected:
        return True
    actual_lines, expected_lines = actual.splitlines(), expected.splitlines()
    if len(actual_lines) != len(expected_lines):
        return False
    for actual_line, expected_line in zip(actual_lines, expected_lines, strict=True):
        actual_tokens, expected_tokens = actual_line.split(), expected_line.split()
        if len(actual_tokens) != len(expected_tokens):
            return False
        for got, want in zip(actual_tokens, expected_tokens, strict=True):
            if got != want and not _close(got, want, rel_tol, abs_tol):
                return False
    return True


def _close(got: str, want: str, rel_tol: float, abs_tol: float) -> bool:
    # Only when the EXPECTED answer is fractional. If the task expects 1326, then
    # 1326.0 is wrong: that is exactly the int/float bug class RunBugRun labels
    # type_conversion, and tolerating it hid 4 real bugs in the pilot.
    if not any(char in want for char in ".eE"):
        return False
    try:
        got_value, want_value = float(got), float(want)
    except ValueError:
        return False
    if math.isnan(got_value) or math.isnan(want_value):
        return False  # NaN never equals a real expected answer
    return math.isclose(got_value, want_value, rel_tol=rel_tol, abs_tol=abs_tol)


STDIN_HARNESS_MAIN = """
payload = json.load(sys.stdin)
cap = payload["max_output_bytes"]
preview = payload["preview_chars"]
with open("tool.py", "w", encoding="utf-8") as handle:
    handle.write(payload["code"])


def limit_output():
    resource.setrlimit(resource.RLIMIT_FSIZE, (cap, cap))


results = []
for index, case in enumerate(payload["tests"]):
    with open("out", "wb") as out, open("err", "wb") as err:
        proc = subprocess.Popen(
            [sys.executable, "tool.py"], stdin=subprocess.PIPE, stdout=out, stderr=err,
            preexec_fn=limit_output,
        )
        timed_out = False
        try:
            proc.communicate(case["input"].encode("utf-8"), timeout=payload["timeout_s"])
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            timed_out = True
    with open("out", "rb") as handle:
        actual = handle.read(cap).decode("utf-8", "replace")
    with open("err", "rb") as handle:
        stderr = handle.read(cap).decode("utf-8", "replace")
    returned = proc.returncode
    code = returned if returned is None or returned >= 0 else 128 - returned
    matches = outputs_match(
        actual, case["output"], rel_tol=payload["rel_tol"], abs_tol=payload["abs_tol"]
    )
    passed = not timed_out and code == 0 and matches
    results.append({
        "index": index, "passed": passed, "timed_out": timed_out, "exit_code": code,
        "actual": "" if passed else actual[:preview], "stderr": "" if passed else stderr[:preview],
    })
print(json.dumps({"results": results}))
"""

# The harness compares outputs with the very functions tested on the host.
STDIN_HARNESS = "\n".join(
    [
        STDIN_HARNESS_IMPORTS,
        inspect.getsource(normalize_output),
        inspect.getsource(outputs_match),
        inspect.getsource(_close),
        STDIN_HARNESS_MAIN,
    ]
)


# --- function-call mode ----------------------------------------------------------

# Runs ONE typed case: import the tool, call the entrypoint, print the value as JSON.
# The tool's own stdout is redirected to stderr so printing cannot corrupt the reply.
FUNCTION_DRIVER = """
import contextlib, importlib.util, json, sys

payload = json.load(open("payload.json", encoding="utf-8"))
case = payload["tests"][int(sys.argv[1])]
spec = importlib.util.spec_from_file_location("tool", "tool.py")
module = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(sys.stderr):
    spec.loader.exec_module(module)

wanted = payload["entrypoint"]
func = getattr(module, wanted, None)
if not callable(func):
    defined = sorted(
        name
        for name, value in vars(module).items()
        if callable(value) and not name.startswith("_")
        and getattr(value, "__module__", None) == "tool"
    )
    if len(defined) == 1:
        func = getattr(module, defined[0])
    else:
        sys.stderr.write("TV_NO_ENTRYPOINT: wanted %r, module defines %r" % (wanted, defined))
        raise SystemExit(3)

args = case["input"]
with contextlib.redirect_stdout(sys.stderr):
    value = func(**args) if isinstance(args, dict) else func(args)
sys.stdout.write(json.dumps({"value": value}, default=str))
"""

FUNCTION_HARNESS_MAIN = """
payload = json.load(sys.stdin)
cap = payload["max_output_bytes"]
preview = payload["preview_chars"]
for name, text in (("tool.py", payload["code"]), ("driver.py", payload["driver"])):
    with open(name, "w", encoding="utf-8") as handle:
        handle.write(text)
with open("payload.json", "w", encoding="utf-8") as handle:
    json.dump(payload, handle)


def limit_output():
    resource.setrlimit(resource.RLIMIT_FSIZE, (cap, cap))


results = []
for index, case in enumerate(payload["tests"]):
    with open("out", "wb") as out, open("err", "wb") as err:
        proc = subprocess.Popen(
            [sys.executable, "driver.py", str(index)], stdout=out, stderr=err,
            preexec_fn=limit_output,
        )
        timed_out = False
        try:
            proc.wait(timeout=payload["timeout_s"])
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            timed_out = True
    with open("out", "rb") as handle:
        raw = handle.read(cap).decode("utf-8", "replace")
    with open("err", "rb") as handle:
        stderr = handle.read(cap).decode("utf-8", "replace")
    returned = proc.returncode
    code = returned if returned is None or returned >= 0 else 128 - returned
    passed = False
    if not timed_out and code == 0:
        try:
            value = json.loads(raw)["value"]
        except Exception:
            code = 4  # the driver did not answer with JSON: treat as a failed call
        else:
            passed = values_match(
                value, case["output"], rel_tol=payload["rel_tol"], abs_tol=payload["abs_tol"]
            )
    results.append({
        "index": index, "passed": passed, "timed_out": timed_out, "exit_code": code,
        "actual": "" if passed else raw[:preview], "stderr": "" if passed else stderr[:preview],
    })
print(json.dumps({"results": results}))
"""

FUNCTION_HARNESS = "\n".join(
    [
        "import json, math, resource, subprocess, sys",
        inspect.getsource(values_match),
        FUNCTION_HARNESS_MAIN,
    ]
)
