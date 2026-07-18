import json

import pandas as pd
import pytest

from src.reporting import posterior_summary, validation_metrics
from src.reporting.posterior_summary import select_candidate_pairs
from src.reporting.validation_metrics import summarize_validation_metrics


def test_validation_metrics_keep_roles_and_units_separate():
    frame = pd.DataFrame({
        "dataset_role": ["calibration", "calibration", "validation", "validation"],
        "variable": ["LAID", "LAID", "LAID", "LAID"],
        "unit": ["m2 m-2"] * 4,
        "observed": [1.0, 3.0, 2.0, 4.0],
        "simulated": [2.0, 4.0, 1.0, 3.0],
    })
    metrics = summarize_validation_metrics(frame)
    assert set(metrics["dataset_role"]) == {"calibration", "validation"}
    assert len(metrics) == 2
    calibration = metrics[metrics["dataset_role"] == "calibration"].iloc[0]
    validation = metrics[metrics["dataset_role"] == "validation"].iloc[0]
    assert calibration["bias"] == pytest.approx(1.0)  # simulated - observed
    assert validation["bias"] == pytest.approx(-1.0)


def test_candidate_pair_selection_is_small_deterministic_and_disjoint():
    candidates = pd.DataFrame([
        {"pair_id": 9, "real_a": "a", "real_b": "b", "phi_total": 10.0,
         "parameter_distance": 5.0, "prediction_distance": float("nan")},
        {"pair_id": 8, "real_a": "a", "real_b": "c", "phi_total": 9.0,
         "parameter_distance": 4.0, "prediction_distance": float("nan")},
        {"pair_id": 7, "real_a": "c", "real_b": "d", "phi_total": 11.0,
         "parameter_distance": 3.0, "prediction_distance": float("nan")},
        {"pair_id": 6, "real_a": "e", "real_b": "f", "phi_total": 12.0,
         "parameter_distance": 2.0, "prediction_distance": float("nan")},
    ])
    selected = select_candidate_pairs(candidates, max_pairs=3)
    assert list(selected["pair_id"]) == [1, 2, 3]
    used = list(selected["real_a"]) + list(selected["real_b"])
    assert len(used) == len(set(used))
    assert list(selected["parameter_distance"]) == [5.0, 3.0, 2.0]


def test_empty_candidate_pairs_keep_stable_schema():
    selected = select_candidate_pairs(pd.DataFrame(), max_pairs=3)
    assert list(selected.columns) == [
        "pair_id", "real_a", "real_b", "phi_a", "phi_b", "phi_total",
        "parameter_distance", "prediction_distance",
    ]


@pytest.mark.parametrize(
    "module,builder",
    [
        (validation_metrics, validation_metrics.build_validation_bundle),
        (posterior_summary, posterior_summary.build_posterior_bundle),
    ],
)
def test_t4_builders_require_explicit_demo_for_science_pending(
    tmp_path, monkeypatch, module, builder
):
    finalize_dir = tmp_path / "calibration_finalize"
    finalize_dir.mkdir()
    (finalize_dir / "calibration_finalize.json").write_text(
        json.dumps({
            "case": "case",
            "engineering_status": "engineering_validated",
            "science_status": "science_pending",
            "scientific_status": "not_assessed",
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        module, "verify_calibration_artifact_manifest", lambda *_args, **_kwargs: {}
    )
    with pytest.raises(ValueError, match="--allow-unvalidated-demo"):
        builder(tmp_path, "case", tmp_path / "out")
