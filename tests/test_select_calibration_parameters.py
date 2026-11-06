import json

import pandas as pd
import pytest

from src.sensitivity.select_calibration_parameters import (
    build_selection_proposal,
    select_by_domain,
)


def _summary(status="science_validated"):
    return pd.DataFrame(
        [
            ("general_genetic", "A", 0.6, status),
            ("general_genetic", "B", 0.3, status),
            ("general_genetic", "C", 0.1, status),
            ("water_nitrogen_response", "B", 0.7, status),
            ("water_nitrogen_response", "D", 0.2, status),
            ("water_nitrogen_response", "E", 0.1, status),
        ],
        columns=[
            "ranking_domain",
            "parameter",
            "cross_season_mean_score",
            "data_status",
        ],
    )


def test_selection_reaches_threshold_in_each_domain_then_takes_union():
    selected, coverage = select_by_domain(_summary(), threshold=0.9)
    assert set(selected["parameter"]) == {"A", "B", "D"}
    assert len(selected) == 3
    assert set(coverage["selected_count"]) == {2}
    assert all(coverage["selected_contribution"] >= 0.9 - 1e-12)
    b = selected.set_index("parameter").loc["B"]
    assert b["selected_domain_count"] == 2


def test_selection_normalizes_domain_totals_and_breaks_ties_by_parameter():
    frame = _summary()
    frame.loc[frame["ranking_domain"].eq("general_genetic"), "cross_season_mean_score"] *= 10
    selected, _ = select_by_domain(frame, threshold=0.6)
    general = selected.loc[selected["general_genetic_selected"]]
    assert general.iloc[0]["parameter"] == "A"


def test_provisional_evidence_requires_explicit_override(tmp_path):
    source = tmp_path / "summary.csv"
    _summary("science_pending").to_csv(source, index=False)
    with pytest.raises(ValueError, match="not science_validated"):
        build_selection_proposal(source, tmp_path / "blocked")

    manifest_path = build_selection_proposal(
        source, tmp_path / "allowed", allow_provisional=True
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["proposal_only"] is True
    assert manifest["automatic_bounds_change"] is False
    assert manifest["union_parameter_count"] == 3


def test_inapplicable_parameter_is_excluded_before_domain_normalization():
    frame = _summary()
    selected, coverage = select_by_domain(
        frame, threshold=0.9, excluded_parameters=("B",)
    )
    assert "B" not in set(selected["parameter"])
    assert set(selected["parameter"]) == {"A", "C", "D", "E"}
    assert all(coverage["selected_contribution"] >= 0.9 - 1e-12)
