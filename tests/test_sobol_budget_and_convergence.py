import json
from pathlib import Path

import pandas as pd
import pytest

from src.sensitivity.sobol_convergence import analyze_convergence
from tools.build_formal_sobol import build_campaign, resolve_budget


ROOT = Path(__file__).resolve().parents[1]
BUDGETS = ROOT / "configs" / "sa" / "sobol_budget_profiles.json"
APPROVAL = ROOT / "configs" / "sa" / "approved_topk" / "eggplant_p1_sobol_top16_20260716.json"
BOUNDS = ROOT / "data" / "parameter_registry" / "bounds_frozen" / "eggplant" / "eggplant_p1_xxql2501_v3_20260716.csv"
PROFILE = ROOT / "configs" / "sa" / "eggplant_p1_outputs_v3_legacy.json"
INPUT = ROOT / "data" / "user" / "experiments" / "xxql2501_20260716"


def test_budget_profiles_and_custom_schedule_are_explicit():
    _, standard, source = resolve_budget(BUDGETS, profile="standard")
    assert standard == [64, 128, 256]
    assert source == "profile:standard"
    _, custom, custom_source = resolve_budget(BUDGETS, profile="standard", samples="64,96,192")
    assert custom == [64, 96, 192]
    assert custom_source == "custom_cli_override"
    with pytest.raises(ValueError, match="strictly increasing"):
        resolve_budget(BUDGETS, samples="64,64,128")
    with pytest.raises(ValueError, match=">=32"):
        resolve_budget(BUDGETS, samples="16,32")


def test_campaign_manifest_displays_theoretical_scale(tmp_path):
    campaign = build_campaign(
        output_root=tmp_path / "campaign",
        bounds=BOUNDS,
        approval=APPROVAL,
        output_profile=PROFILE,
        input_dir=INPUT,
        profile="standard",
        build_levels=1,
        random_seed=20261215,
    )
    assert campaign["planned_sample_schedule"] == [64, 128, 256]
    assert campaign["built_sample_schedule"] == [64]
    assert campaign["expected_initial_model_runs"] == 1152
    assert campaign["expected_maximum_model_runs"] == 8064
    assert campaign["user_adjustable"] is True


def _write_formal_case(root: Path, samples: int, scores: dict[str, tuple[float, float]]) -> None:
    (root / "sobol_audit").mkdir(parents=True)
    (root / "sobol_bootstrap").mkdir()
    expected_runs = samples * 4
    (root / "run_manifest.yaml").write_text(
        "run_type: sensitivity_sobol_formal_case\n"
        "sobol_approval_id: approved_test\n"
        f"sobol_samples: {samples}\n"
        "sobol_parameter_count: 2\n"
        f"sobol_expected_model_runs: {expected_runs}\n"
        "random_seed: 77\n",
        encoding="utf-8",
    )
    (root / "run_status.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "scientific_status": "validated",
                "n_agents": 4,
                "started_at": "2026-07-16T00:00:00Z",
                "finished_at": "2026-07-16T00:10:00Z",
            }
        ),
        encoding="utf-8",
    )
    quality = json.dumps({"science_validated": True})
    (root / "sobol_audit" / "sobol_run_quality.json").write_text(quality, encoding="utf-8")
    (root / "sobol_bootstrap" / "sobol_bootstrap_quality.json").write_text(quality, encoding="utf-8")
    pd.DataFrame({"run_id": range(expected_runs)}).to_csv(
        root / "sa_sen_sobol.sobol.obs.csv", index=False
    )
    rows = []
    for observation, (p1, p2) in scores.items():
        rows.extend(
            [
                {"observation": observation, "parameter": "P1", "estimable": True, "ST": p1},
                {"observation": observation, "parameter": "P2", "estimable": True, "ST": p2},
            ]
        )
    pd.DataFrame(rows).to_csv(
        root / "sobol_bootstrap" / "sobol_bootstrap_indices.csv", index=False
    )


def test_convergence_result_exposes_executed_and_planned_scale(tmp_path):
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "profile_id": "test",
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
    scores_a = {
        "tn2_adaps": (0.8, 0.2),
        "tn2_laixs": (0.7, 0.3),
        "tn2_cwams": (0.75, 0.25),
        "tn2_yield_hwams": (0.9, 0.1),
    }
    scores_b = {
        "tn2_adaps": (0.79, 0.21),
        "tn2_laixs": (0.72, 0.28),
        "tn2_cwams": (0.74, 0.26),
        "tn2_yield_hwams": (0.88, 0.12),
    }
    case64 = tmp_path / "n64"
    case128 = tmp_path / "n128"
    _write_formal_case(case64, 64, scores_a)
    _write_formal_case(case128, 128, scores_b)
    campaign_path = tmp_path / "campaign.json"
    campaign_path.write_text(
        json.dumps(
            {
                "budget_profile": "standard",
                "schedule_source": "profile:standard",
                "planned_sample_schedule": [64, 128, 256],
                "expected_maximum_model_runs": 8064,
                "user_adjustable": True,
            }
        ),
        encoding="utf-8",
    )
    result = analyze_convergence(
        [case64, case128],
        profile,
        campaign_path,
        tmp_path / "out",
        top_k=1,
    )
    assert result["science_validated"]
    assert result["decision"] == "stop_at_current_scale"
    assert result["executed_sample_schedule"] == [64, 128]
    assert result["executed_model_runs"] == 768
    assert result["maximum_planned_model_runs"] == 8064
    assert result["user_adjustable"] is True
    assert (tmp_path / "out" / "sobol_run_scale.csv").is_file()


def test_sobol_convergence_preserves_two_ranking_domains(tmp_path):
    """Sobol convergence must rank within each ranking_domain separately and
    never average across domains. A parameter important only in one domain
    must not be diluted by the other domain (plan §3 W3).

    Construct the case the plan describes: P1 important only in
    general_genetic, P2 important only in water_nitrogen_response. The
    per-domain rankings must keep them separate, and the convergence verdict
    is the AND over both domains.
    """
    profile = tmp_path / "profile_domains.json"
    profile.write_text(
        json.dumps(
            {
                "profile_id": "test_two_domain",
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
    # P1 dominates general_genetic; P2 dominates water_nitrogen_response.
    # Same pattern at both sample levels so both domains converge.
    scores = {
        "tn2_adaps": (0.9, 0.1),       # general_genetic: P1 >> P2
        "tn2_lai_auc": (0.9, 0.1),     # general_genetic: P1 >> P2
        "wn_water_n3_lai_auc": (0.1, 0.9),  # water_nitrogen_response: P2 >> P1
    }
    case64 = tmp_path / "n64"
    case128 = tmp_path / "n128"
    _write_formal_case(case64, 64, scores)
    _write_formal_case(case128, 128, scores)
    campaign_path = tmp_path / "campaign.json"
    campaign_path.write_text(
        json.dumps(
            {
                "budget_profile": "standard",
                "schedule_source": "profile:standard",
                "planned_sample_schedule": [64, 128, 256],
                "expected_maximum_model_runs": 8064,
                "user_adjustable": True,
            }
        ),
        encoding="utf-8",
    )
    result = analyze_convergence([case64, case128], profile, campaign_path, tmp_path / "out", top_k=1)

    # 1. Both ranking domains appear and are kept separate in every comparison,
    #    and both converge (spearman/jaccard at ~1.0).
    domain_rows = {d["ranking_domain"]: d for d in result["comparisons"][0]["ranking_domains"]}
    assert set(domain_rows) == {"general_genetic", "water_nitrogen_response"}
    for row in domain_rows.values():
        assert row["passes"] is True
        assert row["top_k_jaccard"] == 1.0
        assert row["max_top_k_rank_shift"] == 0.0
        assert row["spearman"] == pytest.approx(1.0)

    # 2. The per-domain rankings keep P1/P2 separated (no cross-domain averaging):
    #    general_genetic ranks P1 first, water_nitrogen_response ranks P2 first.
    rankings = pd.read_csv(tmp_path / "out" / "sobol_scale_rankings.csv")
    gg = rankings[rankings["ranking_domain"].eq("general_genetic") & rankings["base_samples"].eq(64)].sort_values("rank")
    wn = rankings[rankings["ranking_domain"].eq("water_nitrogen_response") & rankings["base_samples"].eq(64)].sort_values("rank")
    assert gg.iloc[0]["parameter"] == "P1"
    assert wn.iloc[0]["parameter"] == "P2"

    # 3. If one domain fails to converge, the overall verdict must fail even
    #    though the other domain converged (no cross-domain averaging rescues it).
    scores_diverged = {
        "tn2_adaps": (0.9, 0.1),
        "tn2_lai_auc": (0.9, 0.1),
        "wn_water_n3_lai_auc": (0.1, 0.9),  # n64: P2 first
    }
    scores_diverged_b = {
        "tn2_adaps": (0.9, 0.1),
        "tn2_lai_auc": (0.9, 0.1),
        "wn_water_n3_lai_auc": (0.9, 0.1),  # n128: P1 first -> WN domain diverges
    }
    case64b = tmp_path / "n64b"
    case128b = tmp_path / "n128b"
    _write_formal_case(case64b, 64, scores_diverged)
    _write_formal_case(case128b, 128, scores_diverged_b)
    result_b = analyze_convergence([case64b, case128b], profile, campaign_path, tmp_path / "out_b", top_k=1)
    assert result_b["science_validated"] is False
    wn_domain = next(d for d in result_b["comparisons"][0]["ranking_domains"] if d["ranking_domain"] == "water_nitrogen_response")
    assert wn_domain["passes"] is False
