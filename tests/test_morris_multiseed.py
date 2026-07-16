import json
from pathlib import Path

import pandas as pd
import pytest

from src.sensitivity.morris_multiseed import analyze_multiseed
from tools.build_formal_morris import DEFAULT_SEEDS, validate_seed_plan


def _write_case(
    root: Path,
    seed: int,
    parameter_order: list[str],
    *,
    bounds_sha256: str = "",
    input_manifest_sha256: str = "",
    output_profile_sha256: str = "",
    observations: list[str] | None = None,
) -> Path:
    root.mkdir(parents=True)
    (root / "morris_audit").mkdir()
    manifest_lines = [f"run_type: sensitivity_formal_case", f"random_seed: {seed}"]
    if bounds_sha256:
        manifest_lines.append(f"bounds_sha256: {bounds_sha256}")
    if input_manifest_sha256:
        manifest_lines.append(f"input_manifest_sha256: {input_manifest_sha256}")
    if output_profile_sha256:
        manifest_lines.append(f"output_profile_sha256: {output_profile_sha256}")
    (root / "run_manifest.yaml").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    (root / "run_status.json").write_text(
        json.dumps({"status": "completed", "scientific_status": "validated"}), encoding="utf-8"
    )
    for name in ("morris_run_quality.json", "morris_result_quality.json"):
        (root / "morris_audit" / name).write_text(
            json.dumps({"science_validated": True}), encoding="utf-8"
        )
    rows = []
    used_observations = observations or ["tn2_adaps", "tn2_laixs", "tn2_cwams", "tn2_yield_hwams"]
    scores = {parameter: float(len(parameter_order) - index) for index, parameter in enumerate(parameter_order)}
    for observation in used_observations:
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


def test_multiseed_keeps_general_and_water_nitrogen_rankings_separate(tmp_path):
    profile = tmp_path / "profile_domains.json"
    profile.write_text(
        json.dumps(
            {
                "treatments": [2, 10],
                "features": ["ADAPS", "LAI_AUC"],
                "lai_time_points": [],
                "fruit_time_points": [],
                "response_groups": {
                    "phenology": ["ADAPS", "LAI_AUC"],
                    "water_response": ["WATER_LAI_AUC"],
                },
                "ranking_domains": {
                    "general_genetic": ["phenology"],
                    "water_nitrogen_response": ["water_response"],
                },
            }
        ),
        encoding="utf-8",
    )

    cases = []
    for seed in (11, 22):
        case = _write_case(tmp_path / f"domain_seed_{seed}", seed, ["P1", "P2"])
        rows = [
            {"observation_name": "tn2_adaps", "parameter_name": "P1", "n_samples": 30, "sen_mean_abs": 9.0},
            {"observation_name": "tn2_adaps", "parameter_name": "P2", "n_samples": 30, "sen_mean_abs": 1.0},
            {"observation_name": "tn2_lai_auc", "parameter_name": "P1", "n_samples": 30, "sen_mean_abs": 9.0},
            {"observation_name": "tn2_lai_auc", "parameter_name": "P2", "n_samples": 30, "sen_mean_abs": 1.0},
            {"observation_name": "wn_water_n3_lai_auc", "parameter_name": "P1", "n_samples": 30, "sen_mean_abs": 1.0},
            {"observation_name": "wn_water_n3_lai_auc", "parameter_name": "P2", "n_samples": 30, "sen_mean_abs": 9.0},
        ]
        pd.DataFrame(rows).to_csv(case / "sa_sen_morris.mio", index=False)
        cases.append(case)

    result = analyze_multiseed(cases, profile, tmp_path / "out_domains", top_k=1)
    assert result["stable"] is True
    assert result["ranking_domains"] == ["general_genetic", "water_nitrogen_response"]
    proposal = pd.read_csv(tmp_path / "out_domains" / "morris_topk_proposal.csv")
    selected = {
        row.ranking_domain: row.parameter
        for row in proposal.itertuples(index=False)
    }
    assert selected == {"general_genetic": "P1", "water_nitrogen_response": "P2"}


def test_morris_rejects_mixed_profile_input_or_bounds_hashes(tmp_path):
    """A multi-seed consensus mixing different bounds/input/profile hashes
    is meaningless and must be rejected (plan §7)."""
    profile = _write_profile(tmp_path / "profile.json")
    case_a = _write_case(
        tmp_path / "seed_a", 11, ["P1", "P2"],
        bounds_sha256="aaa", input_manifest_sha256="bbb", output_profile_sha256="ccc",
    )
    case_b = _write_case(
        tmp_path / "seed_b", 22, ["P1", "P2"],
        bounds_sha256="DIFFERENT", input_manifest_sha256="bbb", output_profile_sha256="ccc",
    )
    with pytest.raises(ValueError, match="provenance hashes differ"):
        analyze_multiseed([case_a, case_b], profile, tmp_path / "out")


def test_morris_requires_exact_164_outputs_and_both_domains(tmp_path):
    """A formal profile (carrying observation_count) must have exactly the two
    declared ranking domains, and every case must carry the expected number of
    observations (no mixing a stale 136-output case with a 164-output one)."""
    # (a) A formal profile missing one of the two required domains is rejected.
    bad_profile = tmp_path / "bad_domains.json"
    bad_profile.write_text(
        json.dumps(
            {
                "observation_count": 4,
                "treatments": [2],
                "features": ["ADAPS", "LAIXS", "CWAMS", "YIELD_HWAMS"],
                "lai_time_points": [],
                "fruit_time_points": [],
                "response_groups": {"phenology": ["ADAPS"]},
                "ranking_domains": {"general_genetic": ["phenology"]},
            }
        ),
        encoding="utf-8",
    )
    case_a = _write_case(tmp_path / "seed_a", 11, ["P1", "P2"])
    case_b = _write_case(tmp_path / "seed_b", 22, ["P1", "P2"])
    with pytest.raises(ValueError, match="exactly the two ranking domains"):
        analyze_multiseed([case_a, case_b], bad_profile, tmp_path / "out")

    # (b) A case whose observation count differs from the contract is rejected.
    ok_profile = tmp_path / "ok_profile.json"
    ok_profile.write_text(
        json.dumps(
            {
                "observation_count": 4,
                "treatments": [2],
                "features": ["ADAPS", "LAIXS", "CWAMS", "YIELD_HWAMS"],
                "lai_time_points": [],
                "fruit_time_points": [],
                "response_groups": {
                    "phenology": ["ADAPS", "LAIXS", "CWAMS", "YIELD_HWAMS"],
                },
                "ranking_domains": {
                    "general_genetic": ["phenology"],
                    "water_nitrogen_response": [],
                },
            }
        ),
        encoding="utf-8",
    )
    # seed_b carries only 2 observations while the contract declares 4.
    case_b_short = _write_case(
        tmp_path / "seed_b_short", 22, ["P1", "P2"],
        observations=["tn2_adaps", "tn2_laixs"],
    )
    with pytest.raises(ValueError, match="observations but the contract declares"):
        analyze_multiseed([case_a, case_b_short], ok_profile, tmp_path / "out_b")


def test_unstable_morris_domain_is_not_science_validated(tmp_path):
    """When the two ranking domains disagree on stability, science_validated
    must reflect the unstable domain — the result is recorded but not citable
    as a stable science result."""
    profile = _write_profile(tmp_path / "profile.json")
    # Two seeds whose rankings are reversed -> unstable.
    case_a = _write_case(tmp_path / "seed_a", 11, ["P1", "P2"])
    case_b = _write_case(tmp_path / "seed_b", 22, ["P2", "P1"])
    result = analyze_multiseed([case_a, case_b], profile, tmp_path / "out", top_k=1)
    assert result["stable"] is False
    # science_validated must be False when ranking is not stable.
    assert result["science_validated"] is False
