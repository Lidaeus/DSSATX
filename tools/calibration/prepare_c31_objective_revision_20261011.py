"""Read-only comparison of C31/r3 and a non-executable joint-objective proposal."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
C31 = "full_gen_13trt_final_scheme1_tb1_tighten_200x6_20260927"
CURRENT = "eggplant_26sp_n012_formal_20261011_r3"
OUT = ROOT / "configs/calibration_proposals/eggplant_26sp_n012_c31_joint_review_20261011"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    old = ROOT / "workspace/runs" / C31
    current = ROOT / "workspace/runs" / CURRENT
    design_path = ROOT / "configs/runs" / CURRENT / "design.json"
    design = json.loads(design_path.read_text(encoding="utf-8"))
    sources = [old / (C31 + suffix) for suffix in
               (".pst", ".weights.audit.csv", ".adjusted.obs_data.csv", ".6.obs.csv", ".phi.actual.csv")]
    sources += [old / "run_manifest.yaml", design_path,
                design_path.parent / "review_objective_policy.csv", design_path.parent / "calibration_observations.csv",
                current / "result_review/recomputed_metrics.csv",
                ROOT / "configs/calibration_proposals/eggplant_26sp_n012_review_20261011/observation_catalog.csv",
                ROOT / "data/user/experiments/xxql2601_refreshed_20261010/treatment_metadata.csv",
                ROOT / "data/user/experiments/xxql2601_refreshed_20261010/XXQL2601.TMA",
                ROOT / "workspace/candidates/candidate_c31_scheme1_dual_spring_precision/candidate_manifest.json"]
    sources += [ROOT / x["bundle_path"] / "input_manifest.json" for x in design["datasets"]]
    before = {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in sources}

    pst = pyemu.Pst(str(old / (C31 + ".pst")))
    audit = pd.read_csv(old / (C31 + ".weights.audit.csv"))
    audit["obsnme"] = audit.obsnme.str.lower()
    names = {
        "PDAPS": "定植DAP", "ADAPS": "始花DAP", "MDAPS": "旧成熟期DAP",
        "LAIXS": "最大LAI", "CNAMS": "组合植株氮量", "PWADS": "累计采收干产量",
        "PWAIS": "分次采收干产量", "LAIDS": "LAI时序", "LWADS": "叶干重时序",
        "SWADS": "茎干重时序", "CHTDS": "株高时序", "PEN_CTRS": "旧响应/冠层约束",
        "PEN_MONOS": "旧单侧惩罚",
    }
    simulated = pd.read_csv(old / (C31 + ".6.obs.csv"), index_col=0)
    simulated.columns = simulated.columns.str.lower()
    sq = simulated[pst.obs_names].sub(pst.observation_data.obsval, axis=1)
    sq = sq.mul(pst.observation_data.weight, axis=1).pow(2)
    best = sq.sum(axis=1).idxmin()
    adjusted = pd.read_csv(old / (C31 + ".adjusted.obs_data.csv")).set_index("name")
    assert np.allclose(adjusted.loc[pst.obs_names, "weight"], pst.observation_data.weight)
    assert np.allclose(adjusted.loc[pst.obs_names, "value"], pst.observation_data.obsval)
    old_rows = []
    for token, g in audit.groupby("sim_token", sort=False):
        ids = g.obsnme.tolist()
        old_rows.append(dict(token=token, family=names[token], n=len(g),
                             sigma_min=g.sigma.min(), sigma_max=g.sigma.max(),
                             weight_min=g.weight.min(), weight_max=g.weight.max(),
                             configured_phi_budget="not_declared",
                             one_sigma_residual_phi=len(g),
                             iteration6_min_member=str(best),
                             iteration6_min_member_phi=sq.loc[best, ids].sum(),
                             iteration6_ensemble_mean_phi=sq[ids].sum(axis=1).mean()))
    pd.DataFrame(old_rows).to_csv(OUT / "c31_actual_objective_audit.csv", index=False, encoding="utf-8-sig")
    audit.to_csv(OUT / "c31_actual_weights.csv", index=False, encoding="utf-8-sig")

    policy = pd.read_csv(design_path.parent / "review_objective_policy.csv")
    metrics = pd.read_csv(current / "result_review/recomputed_metrics.csv")
    metrics = metrics[metrics.comparison == "final_calibration"]
    actual = policy.merge(metrics[["variable", "weighted_phi", "n", "nrmse_pct"]], on="variable", validate="1:1")
    actual["configured_budget_pct"] = actual.phi_budget / actual.phi_budget.sum() * 100
    actual["realized_phi_pct"] = actual.weighted_phi / actual.weighted_phi.sum() * 100
    actual.to_csv(OUT / "r3_actual_objective_audit.csv", index=False, encoding="utf-8-sig")

    # These are proposed, not inherited C31 budgets. Existing uncertainty
    # assumptions are held for the nine retained raw-variable families.
    rows = [
        ("CHPDT", "HARVEST_DRY_CUMULATIVE", 20, 45, 25, .20, "kg DM/ha", "all five exact harvest dates"),
        ("HPODW", "HARVEST_DRY_EVENT", 15, 45, 25, .20, "kg DM/ha", "five event increments"),
        ("N_FRESH_CONTRAST", "N_RESPONSE", 8, 6, 1500, .20, "kg fresh/ha", "N1-N0 and N2-N0 within each water level"),
        ("W_FRESH_CONTRAST", "W_RESPONSE", 5, 6, 1500, .20, "kg fresh/ha", "W2-W1 and W3-W1 within each N level"),
        ("N2_SIGN_PENALTY", "N_RESPONSE_DIRECTION", 2, 3, 1500, .20, "kg fresh/ha", "soft max(0,-simulated N2-N0); observed target zero"),
        ("LAID", "CANOPY_LAI", 8, 36, .05, .10, "m2/m2", "raw measured-date state"),
        ("LWAD", "LEAF_DRY_MASS", 6, 36, 20, .15, "kg DM/ha", "raw measured-date state"),
        ("SWAD", "STEM_DRY_MASS", 6, 36, 25, .15, "kg DM/ha", "raw measured-date state"),
        ("CHTD", "HEIGHT", 3, 36, .03, .10, "m", "raw measured-date state"),
        ("LEAF_N_PCT", "LEAF_N_CONCENTRATION", 7, 36, .15, .10, "% dry mass", "PlantN LN%D"),
        ("STEM_N_PCT", "STEM_N_CONCENTRATION", 7, 36, .15, .10, "% dry mass", "PlantN SN%D"),
        ("FRUIT_N_PCT", "FRUIT_N_CONCENTRATION", 6, 27, .15, .20, "% dry mass", "approved mature fruit proxy; exact sampling dates"),
        ("ADAP", "ANTHESIS", 3, 9, 2, 0, "day", "TMA ADAT minus PDAT; not flowering/fruit-setting-start sheet"),
        ("VWC", "SOIL_WATER", 4, 135, .01, .08, "cm3/cm3", "post-initial observed soil layers and dates"),
    ]
    proposed_policy = pd.DataFrame(rows, columns=["variable", "family", "phi_budget", "n_targets",
                                                   "sigma_floor", "cv_model", "unit", "operator"])
    proposed_policy["transform"] = "raw"
    proposed_policy["approved"] = False
    assert proposed_policy.phi_budget.sum() == 100
    proposed_policy.to_csv(OUT / "proposed_objective_policy.csv", index=False, encoding="utf-8-sig")

    catalog = pd.read_csv(sources[10])
    catalog = catalog[(catalog.season_id == "26SP") & (catalog.dataset_role == "calibration")].copy()
    base_vars = policy.variable.tolist() + ["CHPDT"]
    targets = catalog[catalog.variable.isin(base_vars)].copy()
    targets = targets.drop(columns=["phi_budget", "family", "sigma_floor", "cv_model", "sigma_eff", "final_weight"])
    targets = targets.merge(proposed_policy[["variable", "family", "phi_budget", "sigma_floor", "cv_model"]], on="variable", validate="m:1")
    targets["sigma_eff"] = np.sqrt(targets.replicate_sd.fillna(0)**2 + targets.sigma_floor**2 + (targets.cv_model*targets.observed)**2)
    targets["sigma_source"] = "measured_SD_n_eff_1_plus_proposed_floor_CV"
    targets["stratum"] = targets.trno.astype(str)
    targets["parent_observations"] = ""

    metadata = pd.read_csv(sources[11]).set_index(["water_level", "nitrogen_level"])
    terminal = catalog[catalog.variable == "CHFPW"].sort_values("date").groupby("trno").tail(1).set_index("trno")
    derived = []

    def contrast(w_high: str, n_high: str, w_low: str, n_low: str, variable: str, stratum: str) -> None:
        high = int(metadata.loc[(w_high, n_high), "treatment"])
        low = int(metadata.loc[(w_low, n_low), "treatment"])
        h, l = terminal.loc[high], terminal.loc[low]
        assert h.date == l.date
        obs = float(h.observed-l.observed)
        # Covariance between treatment means is unknown; zero cross-treatment
        # covariance is an explicit proposal assumption, not an audited fact.
        sd = np.hypot(float(h.replicate_sd), float(l.replicate_sd))
        sig = np.sqrt(sd**2 + 1500**2 + (.2*abs(obs))**2)
        parent = f"CHFPW:T{high}:{h.date};CHFPW:T{low}:{l.date}"
        derived.append(dict(season_id="26SP", trno=high, paired_trno=low, date=h.date,
                            variable=variable, unit="kg fresh/ha", observed=obs, replicate_sd=sd,
                            n_eff=1, sigma_eff=sig, dataset_role="calibration", stratum=stratum,
                            source_file="observation_catalog.csv:terminal CHFPW",
                            parent_observations=parent, sigma_source="parent_SD_quadrature_covariance_assumed_zero_plus_floor_CV"))
        if variable == "N_FRESH_CONTRAST" and n_high == "N2":
            assert obs > 0
            derived.append(dict(derived[-1], variable="N2_SIGN_PENALTY", observed=0.,
                                sigma_source="same_sigma_as_parent_N2_minus_N0_contrast",
                                observation_operator="max(0,-simulated_parent_contrast)"))

    for w in ("W1", "W2", "W3"):
        for n in ("N1", "N2"):
            contrast(w, n, w, "N0", "N_FRESH_CONTRAST", w)
    for n in ("N0", "N1", "N2"):
        for w in ("W2", "W3"):
            contrast(w, n, "W1", n, "W_FRESH_CONTRAST", n)
    lines = sources[12].read_text(encoding="utf-8").splitlines()
    header = next(x.split() for x in lines if x.startswith("@TRNO"))
    for line in lines:
        vals = line.split()
        if len(vals) != len(header) or not vals[0].isdigit():
            continue
        data = dict(zip(header, vals))
        tn = int(data["@TRNO"])
        if tn not in range(4, 13):
            continue
        observed = int(data["ADAT"])-int(data["PDAT"])
        assert observed == 37  # Both codes in this frozen source are in 2026.
        derived.append(dict(season_id="26SP", trno=tn, date="2026-04-20", variable="ADAP",
                            unit="day", observed=observed, replicate_sd=0., n_eff=1,
                            sigma_eff=2., dataset_role="calibration", stratum=str(tn),
                            source_file="XXQL2601.TMA:ADAT/PDAT", parent_observations="TMA ADAT/PDAT",
                            sigma_source="proposed_2_day_tolerance_shared_date_not_nine_independent_measurements"))
    derived = pd.DataFrame(derived).merge(proposed_policy[["variable", "family", "phi_budget", "sigma_floor", "cv_model"]], on="variable", validate="m:1")
    targets = pd.concat([targets, derived], ignore_index=True)
    for family, idx in targets.groupby("family").groups.items():
        part = targets.loc[idx]
        ns = part.stratum.nunique()
        counts = part.groupby("stratum").stratum.transform("size")
        multiplier = np.sqrt(part.phi_budget/(ns*counts))
        targets.loc[idx, "base_weight"] = 1/part.sigma_eff
        targets.loc[idx, "group_multiplier"] = multiplier
        targets.loc[idx, "proposed_weight"] = multiplier/part.sigma_eff
    targets["approved"] = False
    targets["execution_enabled"] = False
    targets["source_catalog_status"] = targets["status"]
    targets["status"] = "proposed_primary_awaiting_review"
    assert len(targets) == 492
    assert set(targets.trno.astype(int)) == set(range(4, 13))
    assert targets.sigma_eff.gt(0).all() and np.isfinite(targets.proposed_weight).all()
    for family, g in targets.groupby("family"):
        assert np.isclose(((g.proposed_weight*g.sigma_eff)**2).sum(), g.phi_budget.iloc[0])
    targets.to_csv(OUT / "proposed_calibration_targets.csv", index=False, encoding="utf-8-sig")
    targets[targets.variable.isin(["N_FRESH_CONTRAST", "W_FRESH_CONTRAST", "N2_SIGN_PENALTY"])].to_csv(
        OUT / "proposed_response_targets.csv", index=False, encoding="utf-8-sig")

    summary = dict(
        schema="non_executable_c31_joint_objective_review_v1", status="awaiting_user_review",
        approved=False, executable=False, design_id=OUT.name,
        c31_reference_run=C31, current_run=CURRENT, datasets=design["datasets"],
        proposed_phi_budget_total=100, target_count=492,
        objective_policy="proposed_objective_policy.csv", target_catalog="proposed_calibration_targets.csv",
        joint_execution=dict(staged_calibration=False, noptmax=6, ies_num_reals=200, workers=6,
                             initial_method="Sobol within unchanged frozen bounds; physical/output feasibility screening only",
                             seed=20261011, no_observation_noise=True, relative_phi_screening=False,
                             active_parameters=design["eligible_active_parameters"],
                             bounds_id=design["bounds_id"], parameter_start="frozen init, no r3 staged or C31 posterior warm start",
                             no_automatic_budget_bounds_or_parameter_activation_changes=True,
                             failed_preflight_action="report concrete failure and proposed change before execution"),
        pending_implementation=["joint-only entry point", "exact-date cumulative harvest and anthesis operators",
                                "metadata-driven N/W contrasts and soft sign operator", "all-target forward readback and PEST Phi identity"],
        statistical_contract="fixed-budget correlated composite loss; not independent chi-square likelihood or posterior sample",
        c31_iteration6_audit=dict(n_total_records=len(simulated), n_nonbase_records=int((simulated.index.astype(str) != "base").sum()),
                                 min_member=str(best), min_phi=float(sq.loc[best].sum()),
                                 mean_phi=float(sq.sum(axis=1).mean()),
                                 missing_maturity_simulation="all final MDAPS are -99; constant Phi 449.0176",
                                 c31_candidate_is_not_this_min_member=True),
        source_hashes=before,
    )
    assert len(summary["joint_execution"]["active_parameters"]) == 42
    (OUT / "proposal.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    assert before == {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in sources}
    receipt = dict(status="proposal_checks_passed_not_runtime_preflight", source_files_unchanged=True,
                   checks=["C31 PST/adjusted weights agree", "492 calibration-only targets", "14 budgets sum to 100",
                           "each family one-sigma loss equals declared budget", "42 unchanged free parameters",
                           "no old N3 or 2025 contrast included", "no execution enabled"],
                   artifact_hashes={p.name: sha(p) for p in OUT.iterdir() if p.is_file() and p.name != "review_receipt.json"})
    (OUT / "review_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"directory": str(OUT), "targets": len(targets), "budgets": 100,
                      "source_files_unchanged": True, "executable": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
