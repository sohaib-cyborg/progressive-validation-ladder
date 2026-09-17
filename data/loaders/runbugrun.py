"""RunBugRun (Python subset) loader.

Raw files, git-ignored, in ``data/runbugrun_py/raw/`` (format: docs/MEMORY.md):
  python_{split}{i}.jsonl.gz    buggy/fixed pairs (RunBugRun release v0.0.1)
  tests_all.jsonl.gz            stdin -> expected stdout, keyed by problem_id
  problem_descriptions.tar.gz   CodeNet HTML statements (RunBugRun ships none)

Programs are stdin/stdout scripts. The request's ``examples`` are the samples from
the statement; ``tests`` are RunBugRun's held-out ground truth (DECISIONS.md).
"""

import gzip
import html
import re
import tarfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from toolvalidator.contracts import CapabilityRequest, IOExample

type Split = Literal["train", "valid", "test"]

TESTS_FILE = "tests_all.jsonl.gz"
DESCRIPTIONS_FILE = "problem_descriptions.tar.gz"

# A heading directly followed by <pre>. The heading may not span another heading.
_HEADING_PRE = re.compile(
    r"<h([23])[^>]*>((?:(?!<h[1-6][\s>]).)*?)</h\1>\s*<pre[^>]*>(.*?)</pre>", re.I | re.S
)
_SAMPLE_OUT = re.compile(r"(?:sample output|output for the sample input)\s*(\d*)", re.I)
_SAMPLE_IN = re.compile(r"sample input\s*(\d*)", re.I)
_BLOCK_END = re.compile(r"<br\s*/?>|</(?:p|h\d|pre|li|div|section|tr)>", re.I)
_TAG = re.compile(r"<[^>]+>")


class RunBugRunEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    entry_id: int
    split: Split
    problem_id: str
    request: CapabilityRequest
    buggy_code: str
    fixed_code: str
    tests: list[IOExample]
    bug_labels: list[str]


@dataclass
class LoadReport:
    """What happened to every row read, so nothing is dropped silently."""

    read: int = 0
    yielded: int = 0
    skipped_no_description: int = 0
    skipped_no_tests: int = 0


class _BugRow(BaseModel):
    id: int
    problem_id: str
    buggy_code: str
    fixed_code: str
    labels: list[str] | None = None


class _TestRow(BaseModel):
    problem_id: str
    input: str
    output: str


def iter_entries(
    raw_dir: Path,
    split: Split,
    *,
    limit: int | None = None,
    report: LoadReport | None = None,
) -> Iterator[RunBugRunEntry]:
    report = report if report is not None else LoadReport()
    rows = _read_bug_rows(raw_dir, split)[:limit]
    pids = {row.problem_id for row in rows}
    tests = _read_tests(raw_dir / TESTS_FILE, pids)
    descriptions = _read_descriptions(raw_dir / DESCRIPTIONS_FILE, pids)
    requests: dict[str, CapabilityRequest] = {}
    for row in rows:
        report.read += 1
        pid = row.problem_id
        if pid not in requests and pid in descriptions:
            requests[pid] = parse_description(pid, descriptions[pid])
        if pid not in requests or not requests[pid].description:
            report.skipped_no_description += 1
            continue
        if not tests.get(pid):
            report.skipped_no_tests += 1
            continue
        report.yielded += 1
        yield RunBugRunEntry(
            entry_id=row.id,
            split=split,
            problem_id=pid,
            request=requests[pid],
            buggy_code=row.buggy_code,
            fixed_code=row.fixed_code,
            tests=tests[pid],
            bug_labels=row.labels or [],
        )


def parse_description(problem_id: str, raw_html: str) -> CapabilityRequest:
    """Statement text plus the "Sample Input N" / "Sample Output N" pairs it contains."""
    inputs: dict[str, str] = {}
    outputs: dict[str, str] = {}
    for _, heading, pre in _HEADING_PRE.findall(raw_html):
        title = _text(heading)
        if match := _SAMPLE_OUT.search(title):
            outputs[match[1] or "1"] = _pre_text(pre)
        elif match := _SAMPLE_IN.search(title):
            inputs[match[1] or "1"] = _pre_text(pre)
    paired = sorted(inputs.keys() & outputs.keys(), key=int)
    return CapabilityRequest(
        name=problem_id,
        description=_text(raw_html),
        examples=[IOExample(input=inputs[k], output=outputs[k]) for k in paired],
    )


def _read_bug_rows(raw_dir: Path, split: Split) -> list[_BugRow]:
    files = sorted(raw_dir.glob(f"python_{split}[0-9]*.jsonl.gz"))
    if not files:
        raise FileNotFoundError(f"no python_{split}*.jsonl.gz in {raw_dir}")
    rows: list[_BugRow] = []
    for path in files:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            rows.extend(_BugRow.model_validate_json(line) for line in f if line.strip())
    return rows


def _read_tests(path: Path, pids: set[str]) -> dict[str, list[IOExample]]:
    tests: dict[str, list[IOExample]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            row = _TestRow.model_validate_json(line)
            if row.problem_id in pids:
                tests.setdefault(row.problem_id, []).append(
                    IOExample(input=row.input, output=row.output)
                )
    return tests


def _read_descriptions(path: Path, pids: set[str]) -> dict[str, str]:
    # Members are only read, never extracted, so archive paths can't escape.
    found: dict[str, str] = {}
    with tarfile.open(path, "r:gz") as tar:
        for member in tar:
            pid = Path(member.name).stem
            if member.isfile() and member.name.endswith(".html") and pid in pids:
                data = tar.extractfile(member)
                if data is not None:
                    found[pid] = data.read().decode("utf-8", errors="replace")
    return found


def _text(fragment: str) -> str:
    text = html.unescape(_TAG.sub("", _BLOCK_END.sub("\n", fragment)))
    lines = [re.sub(r"[ \t\xa0]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _pre_text(fragment: str) -> str:
    text = html.unescape(_TAG.sub("", fragment))
    # HTML drops a single newline directly after <pre>.
    return text.removeprefix("\r\n") if text.startswith("\r\n") else text.removeprefix("\n")
