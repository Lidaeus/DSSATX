import json
from pathlib import Path

import pandas as pd

from src.sensitivity.morris_multiseed import analyze_multiseed
from tools.build_formal_morris import DEFAULT_SEEDS, validate_seed_plan


def _write_case(root: Path, seed: int, parameter_order: list[str]) -> Path:
    root.mkdir(parents=True)
    (root / "morris_audit").mkdir()
    (root / "run_manifest.yaml").write_text(
        f"run_type: sensitivity_formal_case\nrandom_seed: {seed}\n", encoding="utf-8"
    )
    (root / "run_status.json").write_text(
        json.dumps({"status": "completed", "scientific_status": "validated"}), encoding="utf-8"
    )
    for name in ("morris_run_quality.json", "morris_result_quality.json"):
        (root / "morris_audit" / name).write_text(
            json.dumps({"science_validated": True}), encoding="utf-8"
        )
    rows = []
    observations = ["tn2_adaps", "tn2_laixs", "tn2_cwams", "tn2_yield_hwams"]
    scores = {parameter: float(len(parameter_order) - index) for index, parameter in enumerate(parameter_order)}
    for observation in observations:
        for parameter, score in scores.items():
            rows.append(
                {
                    "observation_name": observation,
                    "parameter_name": parameter,
                    "n_samples": 30,
                    "sen_mean_abs": score,
                }
            )
    pd.DataFrame(rows).to_csv(root / "sa_sen_morris.mio", index=False)
    return root


def _write_profile(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "treatments": [2],
                "features": ["ADAPS", "LAIXS", "CWAMS", "YIELD_HWAMS"],
                "lai_time_points": [],
                "fruit_time_points": [],
                "response_groups": {
                    "phenology": ["ADAPS"],
                    "canopy": ["LAIXS"],
                    "biomass": ["CWAMS"],
                    "yield_harvest": ["YIELD_HWAMS"],
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_multiseed_stability_stops_when_rankings_agree(tmp_path):
    profile = _write_profile(tmp_path / "profile.json")
    case_a = _write_case(tmp_path / "seed_a", 11, ["P1", "P2", "P3"])
    case_b = _write_case(tmp_path / "seed_b", 22, ["P1", "P2", "P3"])
    result = analyze_multiseed([case_a, case_b], profile, tmp_path / "out", top_k=2)
    assert result["stable"] is True
    assert result["decision"] == "stop_at_current_seed_count"
    assert result["minimum_pairwise_spearman"] == 1.0
    assert result["minimum_pairwise_top_k_jaccard"] == 1.0
    proposal = pd.read_csv(tmp_path / "out" / "morris_topk_proposal.csv")
    assert set(proposal["parameter"]) == {"P1", "P2"}
    assert set(proposal["selection_class"]) == {"stable_core"}


def test_multiseed_stability_requests_next_seed_when_rankings_disagree(tmp_path):
    profile = _write_profile(tmp_path / "profile.json")
    case_a = _write_case(tmp_path / "seed_a", 11, ["P1", "P2", "P3"])
    case_b = _write_case(tmp_path / "seed_b", 22, ["P3", "P2", "P1"])
    result = analyze_multiseed([case_a, case_b], profile, tmp_path / "out", top_k=1)
    assert result["stable"] is False
    assert result["decision"] == "add_next_prespecified_seed"
    assert result["minimum_pairwise_spearman"] == -1.0
    assert result["minimum_pairwise_top_k_jaccard"] == 0.0
    proposal = pd.read_csv(tmp_path / "out" / "morris_topk_proposal.csv")
    assert set(proposal["parameter"]) == {"P1", "P3"}
    assert set(proposal["selection_class"]) == {"top_k_boundary_union"}


def test_multiseed_rejects_preflight_case(tmp_path):
    profile = _write_profile(tmp_path / "profile.json")
    case_a = _write_case(tmp_path / "seed_a", 11, ["P1", "P2"])
    case_b = _write_case(tmp_path / "seed_b", 22, ["P1", "P2"])
    (case_b / "run_manifest.yaml").write_text(
        "run_type: sensitivity_preflight_case\nrandom_seed: 22\n", encoding="utf-8"
    )
    try:
        analyze_multiseed([case_a, case_b], profile, tmp_path / "out")
    except ValueError as exc:
        assert "non-formal" in str(exc)
    else:
        raise AssertionError("Preflight case should not enter formal stability analysis")


def test_formal_seed_plan_starts_with_two_new_unique_seeds():
    assert validate_seed_plan(DEFAULT_SEEDS) == [20260729, 20260812]
    for invalid in ([20260729], [20260729, 20260729], [20260715, 20260729]):
        try:
            validate_seed_plan(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Invalid formal seed plan accepted: {invalid}")


def test_multiseed_records_but_does_not_rank_failed_formal_case(tmp_path):
    profile = _write_profile(tmp_path / "profile.json")
    case_a = _write_case(tmp_path / "seed_a", 11, ["P1", "P2"])
    case_b = _write_case(tmp_path / "seed_b", 22, ["P1", "P2"])
    failed = _write_case(tmp_path / "seed_failed", 33, ["P2", "P1"])
    (failed / "run_status.json").write_text(
        json.dumps({"status": "completed", "scientific_status": "failed"}), encoding="utf-8"
    )
    (failed / "morris_audit" / "morris_run_audit.json").write_text(
        json.dumps(
            {
                "summary": {
                    "model_failed_runs": 1,
                    "runtime_failed_runs": 0,
                    "fully_valid_trajectories": 29,
                    "expected_trajectories": 30,
                }
            }
        ),
        encoding="utf-8",
    )
    result = analyze_multiseed(
        [case_a, case_b],
        profile,
        tmp_path / "out",
        excluded_case_dirs=[failed],
    )
    assert result["seeds"] == [11, 22]
    assert result["excluded_cases"][0]["seed"] == 33
    assert result["excluded_cases"][0]["model_failed_runs"] == 1
