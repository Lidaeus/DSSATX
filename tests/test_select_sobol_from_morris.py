from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from tools.sa.select_sobol_from_morris import select_parameters


def _result(path: Path, *, stable: bool, rows: list[tuple[str, str, float, int]]) -> Path:
    path.mkdir(parents=True)
    (path / "morris_multiseed_stability.json").write_text(
        json.dumps({"ranking_stable": stable}), encoding="utf-8"
    )
    pd.DataFrame(
        rows,
        columns=["ranking_domain", "parameter", "mean_score", "consensus_rank"],
    ).to_csv(path / "morris_consensus_ranking.csv", index=False)
    return path


def test_selection_requires_recurrence_or_material_single_domain_score(tmp_path: Path):
    rows_a = [
        ("general_genetic", "A", 0.10, 1),
        ("general_genetic", "B", 0.03, 2),
        ("water_nitrogen_response", "A", 0.08, 1),
        ("water_nitrogen_response", "C", 0.01, 2),
    ]
    rows_b = [
        ("general_genetic", "A", 0.09, 1),
        ("general_genetic", "D", 0.021, 2),
        ("water_nitrogen_response", "E", 0.01, 1),
        ("water_nitrogen_response", "F", 0.01, 2),
    ]
    selected, _ = select_parameters(
        {
            "S1": _result(tmp_path / "s1", stable=True, rows=rows_a),
            "S2": _result(tmp_path / "s2", stable=True, rows=rows_b),
        },
        top_k=1,
        minimum_domain_count=2,
        season_specific_score=0.02,
    )
    assert set(selected["parameter"]) == {"A"}


def test_selection_refuses_unstable_morris(tmp_path: Path):
    rows = [
        ("general_genetic", "A", 0.1, 1),
        ("water_nitrogen_response", "A", 0.1, 1),
    ]
    with pytest.raises(ValueError, match="not stable"):
        select_parameters({"S1": _result(tmp_path / "s1", stable=False, rows=rows)})
