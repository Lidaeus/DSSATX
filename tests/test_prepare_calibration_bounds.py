from pathlib import Path

import pandas as pd
import pytest

from tools.prepare_calibration_bounds_from_selection import build_proposal


def _write_source(path: Path):
    pd.DataFrame(
        [
            {"name": "A", "init": 2.0, "lower": 1.0, "upper": 3.0, "status": "active", "pargp": "g", "location": "CUL", "file": "x", "cultivar": "c", "ecotype": "e", "mode": "m"},
            {"name": "B", "init": 5.0, "lower": 4.0, "upper": 6.0, "status": "active", "pargp": "g", "location": "CUL", "file": "x", "cultivar": "c", "ecotype": "e", "mode": "m"},
            {"name": "IC", "init": 0.2, "lower": 0.1, "upper": 0.3, "status": "disabled", "pargp": "ic", "location": "IC", "file": "x", "cultivar": "c", "ecotype": "e", "mode": "m"},
        ]
    ).to_csv(path, index=False)


def test_proposal_keeps_selected_range_and_fixes_other_active_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "tools.prepare_calibration_bounds_from_selection.assert_valid_frozen_bounds",
        lambda _path: [],
    )
    source = tmp_path / "source.csv"
    selection = tmp_path / "selection.csv"
    output = tmp_path / "proposal.csv"
    _write_source(source)
    pd.DataFrame({"parameter": ["A"], "evidence_status": ["science_pending"]}).to_csv(selection, index=False)
    result = build_proposal(source, selection, output, allow_provisional_selection=True).set_index("name")
    assert result.loc["A", "status"] == "active"
    assert result.loc["A", "lower"] == 1.0
    assert result.loc["B", "status"] == "fixed"
    assert result.loc["B", "lower"] == result.loc["B", "upper"] == result.loc["B", "init"]
    assert result.loc["IC", "status"] == "disabled"
    assert output.with_suffix(".yaml").is_file()


def test_provisional_selection_is_rejected_by_default(tmp_path):
    source = tmp_path / "source.csv"
    selection = tmp_path / "selection.csv"
    _write_source(source)
    pd.DataFrame({"parameter": ["A"], "evidence_status": ["science_pending"]}).to_csv(selection, index=False)
    with pytest.raises(ValueError, match="not science_validated"):
        build_proposal(source, selection, tmp_path / "proposal.csv")
