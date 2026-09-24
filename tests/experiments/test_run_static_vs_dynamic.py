"""Tests for the RQ1/RQ2 experiment script (experiments/run_static_vs_dynamic.py)."""

import json
from pathlib import Path

import pytest

from experiments.run_static_vs_dynamic import main

RAW = Path(__file__).resolve().parents[2] / "data" / "runbugrun_py" / "raw"


@pytest.mark.slow
def test_end_to_end_on_two_entries(tmp_path: Path, sandbox_image: str) -> None:
    if not (RAW / "python_valid0.jsonl.gz").exists():
        pytest.skip("RunBugRun raw files not downloaded")
    code = main(
        [
            "--raw-dir",
            str(RAW),
            "--out",
            str(tmp_path),
            "--n",
            "2",
            "--splits",
            "valid",
            "--workers",
            "1",
        ]
    )
    assert code == 0
    rows = [
        json.loads(line) for line in (tmp_path / "static_vs_dynamic.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 4  # 2 entries x (buggy, fixed)
    summary = json.loads((tmp_path / "static_vs_dynamic.summary.json").read_text())
    assert summary["n_tools"] == 4
    assert summary["n_errors"] == 0
    assert summary["seed"] == 20260917
    assert summary["max_tests"] == 25  # the agreed per-program cap is the default
    assert all(row["n_tests"] == min(25, row["n_tests_available"]) for row in rows)
    assert 0.0 <= summary["dynamic"]["slip_rate"] <= 1.0
