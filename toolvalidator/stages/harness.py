"""Comparison rules and the in-sandbox harness text used by S4.

Split out of ``s4_execute`` to keep both files under the size limit (CLAUDE.md §2).
The harness injects the very functions tested here, so the rule has one definition.
"""

import inspect
import math

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
