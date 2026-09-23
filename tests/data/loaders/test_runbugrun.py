"""Tests for the RunBugRun loader (data/loaders/runbugrun.py).

Unit tests use tiny fixtures that copy the two real CodeNet HTML markups
(AtCoder and AOJ, see docs/MEMORY.md). The last test reads the real downloaded
files and is skipped when they are absent (they are git-ignored).
"""

import gzip
import io
import json
import tarfile
from pathlib import Path

import pytest

from data.loaders.runbugrun import LoadReport, iter_entries, parse_description
from toolvalidator.contracts import IOExample

# Real AtCoder files carry a single <span class="lang-en"> (no file mixes en + ja).
ATCODER_HTML = """<span class="lang-en">
<p>Score : <var>200</var> points</p>
<div class="part"><section>
<h3>Problem Statement</h3><p>Print <code>Yes</code> if <var>N</var> &gt; 0.</p>
</section></div>
<div class="part"><section>
<h3>Sample Input 1</h3><pre>4 1
5 4 2 1
</pre>
</section></div>
<div class="part"><section>
<h3>Sample Output 1</h3><pre>Yes
</pre>
<p>Explanation.</p>
</section></div>
<div class="part"><section>
<h3>Sample Input 2</h3><pre>0 1
</pre></section></div>
<div class="part"><section>
<h3>Sample Output 2</h3><pre>No
</pre></section></div>
</span>"""

AOJ_HTML = """<H1>List of Top 3 Hills</H1>
<p>Write a program which prints heights of the top three mountains.</p>
<H2>Output</H2>
<pre>
Height of the 1st mountain
</pre>
<H2>Sample Input 1</H2>
<pre>
1819
2003
</pre>
<H2>Output for the Sample Input 1</H2>

<pre>
2003
1819
</pre>
"""


# --- parse_description ---------------------------------------------------------


def test_atcoder_text_and_paired_samples() -> None:
    parsed = parse_description("p02718", ATCODER_HTML)
    assert parsed.request.description.startswith("Score : 200 points")
    assert "Print Yes if N > 0." in parsed.request.description
    assert parsed.examples == [
        IOExample(input="4 1\n5 4 2 1\n", output="Yes\n"),
        IOExample(input="0 1\n", output="No\n"),
    ]


def test_request_follows_the_upstream_capability_request_schema() -> None:
    # docs/capability_request.md §2: name, capability, description, inputs, outputs, rationale.
    request = parse_description("p02718", ATCODER_HTML).request
    assert request.name == "solve_p02718"
    assert request.capability == "solve_p02718"
    assert [(p.name, p.type) for p in request.inputs] == [("stdin", "string")]
    assert [(p.name, p.type) for p in request.outputs] == [("stdout", "string")]
    assert request.rationale is not None and "p02718" in request.rationale


def test_aoj_output_for_the_sample_input_and_leading_newline() -> None:
    parsed = parse_description("p00001", AOJ_HTML)
    assert parsed.request.description.startswith("List of Top 3 Hills")
    # The <pre> under "Output" is not a sample; the leading newline after <pre> is dropped.
    assert parsed.examples == [IOExample(input="1819\n2003\n", output="2003\n1819\n")]


def test_description_without_samples_has_no_examples() -> None:
    parsed = parse_description(
        "p00000", "<H1>QQ</H1><p>Write a program.</p><H2>Input</H2><p>No input.</p>"
    )
    assert parsed.examples == []
    assert "Write a program." in parsed.request.description


def test_unpaired_sample_is_ignored() -> None:
    html = "<p>x</p><h3>Sample Input 1</h3><pre>1\n</pre><h3>Sample Output 2</h3><pre>2\n</pre>"
    assert parse_description("p1", html).examples == []


# --- iter_entries on a synthetic raw directory ---------------------------------


def _write_jsonl_gz(path: Path, rows: list[dict[str, object]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _write_descriptions(path: Path, docs: dict[str, str]) -> None:
    with tarfile.open(path, "w:gz") as tar:
        for pid, html in docs.items():
            data = html.encode("utf-8")
            info = tarfile.TarInfo(f"problem_descriptions/{pid}.html")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def _bug(entry_id: int, pid: str, labels: list[str] | None) -> dict[str, object]:
    return {
        "id": entry_id,
        "buggy_submission_id": 1,
        "fixed_submission_id": 2,
        "problem_id": pid,
        "user_id": "u1",
        "buggy_code": "print(int(input()) + 2)",
        "fixed_code": "print(int(input()) + 1)",
        "labels": labels,
        "change_count": 1,
        "line_hunks": 1,
    }


@pytest.fixture
def raw_dir(tmp_path: Path) -> Path:
    _write_jsonl_gz(
        tmp_path / "python_valid0.jsonl.gz",
        [
            _bug(1, "p1", ["literal.number.integer.change"]),
            _bug(2, "p_no_desc", None),
            _bug(3, "p_no_tests", []),
        ],
    )
    _write_jsonl_gz(tmp_path / "python_train0.jsonl.gz", [_bug(4, "p1", None)])
    _write_jsonl_gz(
        tmp_path / "tests_all.jsonl.gz",
        [
            {"id": 10, "problem_id": "p1", "input": "1\n", "output": "2\n"},
            {"id": 11, "problem_id": "p1", "input": "5\n", "output": "6\n"},
            {"id": 12, "problem_id": "p_no_desc", "input": "", "output": "x\n"},
        ],
    )
    _write_descriptions(
        tmp_path / "problem_descriptions.tar.gz",
        {"p1": "<p>Add one.</p>", "p_no_tests": "<p>Nothing.</p>"},
    )
    return tmp_path


def test_iter_entries_builds_entries_and_reports_skips(raw_dir: Path) -> None:
    report = LoadReport()
    entries = list(iter_entries(raw_dir, split="valid", report=report))
    assert [e.entry_id for e in entries] == [1]
    entry = entries[0]
    assert entry.split == "valid"
    assert entry.problem_id == "p1"
    assert entry.request.description == "Add one."
    assert entry.request.capability == "solve_p1"
    assert entry.buggy_code == "print(int(input()) + 2)"
    assert entry.fixed_code == "print(int(input()) + 1)"
    assert entry.tests == [
        IOExample(input="1\n", output="2\n"),
        IOExample(input="5\n", output="6\n"),
    ]
    assert entry.bug_labels == ["literal.number.integer.change"]
    assert report == LoadReport(read=3, yielded=1, skipped_no_description=1, skipped_no_tests=1)


def test_iter_entries_selects_split_and_maps_null_labels(raw_dir: Path) -> None:
    entries = list(iter_entries(raw_dir, split="train"))
    assert [(e.entry_id, e.split, e.bug_labels) for e in entries] == [(4, "train", [])]


def test_iter_entries_limit(raw_dir: Path) -> None:
    assert len(list(iter_entries(raw_dir, split="valid", limit=0))) == 0


def test_missing_split_file_is_an_error(raw_dir: Path) -> None:
    with pytest.raises(FileNotFoundError, match="python_test"):
        list(iter_entries(raw_dir, split="test"))


# --- real data (skipped when not downloaded) -----------------------------------

REAL_RAW = Path(__file__).resolve().parents[3] / "data" / "runbugrun_py" / "raw"


@pytest.mark.slow
@pytest.mark.skipif(
    not (REAL_RAW / "python_valid0.jsonl.gz").exists(), reason="RunBugRun raw files not downloaded"
)
def test_real_valid_split_loads() -> None:
    report = LoadReport()
    entries = list(iter_entries(REAL_RAW, split="valid", report=report))
    assert report.read == 2054  # size in the release Manifest
    assert report.yielded == len(entries) > 2000
    first = entries[0]
    assert first.problem_id == "p00000"
    assert first.tests and first.request.description
    assert sum(bool(e.examples) for e in entries) > 0.9 * len(entries)
