from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from src.management.formal_design import load_formal_design
from src.management.nitrogen_sequence import (
    NitrogenSequenceBounds,
    ahp_priority_weights,
    ahp_utility_score,
    decode_pso_position,
    materialize_nitrogen_sequence,
)


DESIGN = Path("configs/management/eggplant_greenhouse_drip_pso_sequence_v3.json")


def test_v3_design_uses_two_current_spring_bundles_and_no_surrogate():
    design = load_formal_design(DESIGN)
    assert [season.year for season in design.seasons] == [2025, 2026]
    assert design.optimizer["algorithm"] == "PSO_AHP_direct_DSSAT"
    payload = json.loads(DESIGN.read_text(encoding="utf-8"))
    assert payload["surrogate_model"] is False
    assert payload["rainfall_as_management_input"] is False
    assert payload["nitrogen_sequence_policy"]["carrier_rows"] == "FE005_only"


def test_pso_codec_repairs_mixed_integer_frequency_timing_and_mass():
    bounds = NitrogenSequenceBounds()
    position = [0.5, 0.4, 0.5, 0.999] + [0.5] * (2 * bounds.maximum_count)
    sequence = decode_pso_position(position, bounds)
    assert sequence.topdress_count == 10
    assert len(sequence.events) == 11
    topdress_daps = [e.dap for e in sequence.events if e.event_role == "topdress"]
    assert all(b - a >= 5 for a, b in zip(topdress_daps, topdress_daps[1:]))
    assert max(topdress_daps) <= 96
    assert abs(sum(e.amount_kg_ha for e in sequence.events) - sequence.total_n_kg_ha) < 1e-8
    assert all(2.0 <= e.amount_kg_ha <= 75.0 for e in sequence.events[1:])


def test_ahp_profiles_pass_consistency_and_fixed_anchor_scoring():
    payload = json.loads(DESIGN.read_text(encoding="utf-8"))
    criteria = payload["criteria"]
    for profile in payload["ahp"]["profiles"].values():
        result = ahp_priority_weights(profile["pairwise_matrix"])
        assert result.consistency_ratio <= 0.10
        assert abs(sum(result.weights) - 1.0) < 1e-10
    balanced = ahp_priority_weights(
        payload["ahp"]["profiles"]["balanced"]["pairwise_matrix"]
    )
    anchors = {
        "mean_fresh_yield": (1000.0, 2000.0),
        "worst_year_fresh_yield": (800.0, 1800.0),
        "seasonal_irrigation_mm": (240.0, 500.0),
        "seasonal_nitrogen_kg_ha": (60.0, 320.0),
        "interannual_yield_gap_fraction": (0.0, 0.30),
    }
    score = ahp_utility_score(
        {
            "mean_fresh_yield": 1500.0,
            "worst_year_fresh_yield": 1300.0,
            "seasonal_irrigation_mm": 370.0,
            "seasonal_nitrogen_kg_ha": 190.0,
            "interannual_yield_gap_fraction": 0.15,
        },
        criteria,
        balanced.weights,
        anchors,
    )
    assert score == pytest.approx(0.5)


@pytest.mark.parametrize(
    ("source", "planting", "treatment"),
    [
        ("data/user/experiments/XXQL2501/XXQL2501.TMX", 25075, 2),
        ("data/user/experiments/XXQL2601/XXQL2601.TMX", 26069, 1),
    ],
)
def test_materializer_rewrites_only_n_carrier_slots_and_preserves_total(
    tmp_path, source, planting, treatment
):
    bounds = NitrogenSequenceBounds()
    sequence = decode_pso_position([0.5] * bounds.vector_size, bounds)
    out = tmp_path / f"year_{planting}"
    manifest = materialize_nitrogen_sequence(
        source, out, sequence, planting, treatment, "pso_test"
    )
    assert manifest["total_n_kg_ha"] == pytest.approx(sequence.total_n_kg_ha)
    assert manifest["phosphorus_potassium_rows_unchanged"] is True
    assert manifest["rainfall_considered"] is False
    with (out / "NitrogenSequence.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == sequence.topdress_count + 1
    assert all(row["fertilizer_code"] == "FE005" for row in rows)
    assert max(int(row["dap"]) for row in rows if row["event_role"] == "topdress") <= 96
    original_non_n = [
        line for line in Path(source).read_text(encoding="utf-8").splitlines()
        if "FE005" not in line
    ]
    written_non_n = [
        line for line in (out / Path(source).name).read_text(encoding="utf-8").splitlines()
        if "FE005" not in line
    ]
    assert written_non_n == original_non_n
