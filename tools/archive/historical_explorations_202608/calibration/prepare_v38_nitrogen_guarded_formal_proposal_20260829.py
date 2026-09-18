"""Prepare (but do not freeze or launch) the v38 nitrogen-guarded formal design."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_BOUNDS = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v37_formal_source_sink_balanced_bounds.csv"
SOURCE_RUN = ROOT / "workspace/runs/e02_formal_v37_fresh_yield_source_sink_200x4_20260829"
SOURCE_CASE = "e02_formal_v37_fresh_source_sink_20260829"
ANCHOR_PARAMS = SOURCE_RUN / "best_member_137_two_season_deterministic_20260829/best_member_137_params.csv"
PROPOSAL = ROOT / "data/parameter_registry/bounds_proposals/eggplant_e02_v38_nitrogen_guarded_formal_bounds_proposal.csv"
CONFIG = ROOT / "configs/runs/e02_formal_v38_nitrogen_guarded_200x6_20260829.draft.json"
AUDIT = ROOT / "workspace/reports/e02_v37_n_response_multiarm_execution_20260829/postrun_analysis/v38_formal_parameter_design.csv"

NITROGEN = {
    "nstfac", "rtno3", "rtnh4", "rtexf", "prolfi", "prosti", "prolff", "prostf",
    "nmobmx", "nvsmob", "nrcvr", "senrte", "fnpgn1", "fnpgn2", "lnref", "nslope",
}
CANOPY_SCALE = {"pgeff", "kcan", "parmax", "phtmax", "lfmax", "slavr", "slaref", "sizref", "sizlf"}
SOURCE_SINK = {"wtfsd", "sfdur", "podur", "porpt", "xfrmax", "xfrt", "cmobmx", "vssink", "atop", "finref"}
WATER_GUARD = {"dswbar", "rwumx", "pormin", "swbar_rec", "yswbar_mid", "rwdth"}
SOIL_N_SUPPLY = {"soil_slpf"}
ACTIVE = NITROGEN | CANOPY_SCALE | SOURCE_SINK | WATER_GUARD | SOIL_N_SUPPLY

# Explicitly retain/widen source-sink ranges implicated by earlier boundary
# diagnostics; all values remain inside the registry's physical hard limits.
OVERRIDES = {
    "phtmax": (50.0, 80.0),
    "wtfsd": (0.25, 0.62),
    "sfdur": (36.0, 65.0),
    "parmax": (35.0, 55.0),
    "xfrmax": (0.10, 0.40),
}


def main() -> int:
    bounds = pd.read_csv(SOURCE_BOUNDS)
    bounds["name"] = bounds["name"].astype(str).str.lower()
    anchor = pd.read_csv(ANCHOR_PARAMS)
    anchor["name"] = anchor["name"].astype(str).str.lower()
    anchor_values = dict(zip(anchor["name"], pd.to_numeric(anchor["value"])))
    posterior = pd.read_csv(SOURCE_RUN / f"{SOURCE_CASE}.3.par.csv")

    rows = []
    audit_rows = []
    for _, source in bounds.iterrows():
        row = source.copy()
        name = str(row["name"])
        if name in anchor_values:
            row["init"] = anchor_values[name]
        if name in ACTIVE:
            row["status"] = "active"
            original_lower, original_upper = float(source["lower"]), float(source["upper"])
            if name in posterior.columns:
                values = pd.to_numeric(posterior[name], errors="coerce")
                pad = 0.10 * (original_upper - original_lower)
                lower = max(original_lower, float(values.quantile(.05)) - pad)
                upper = min(original_upper, float(values.quantile(.95)) + pad)
                lower = min(lower, float(row["init"]))
                upper = max(upper, float(row["init"]))
                row["lower"], row["upper"] = lower, upper
            if name in OVERRIDES:
                row["lower"], row["upper"] = OVERRIDES[name]
        else:
            row["status"] = "fixed"
            row["lower"] = row["init"]
            row["upper"] = row["init"]
        rows.append(row)
        audit_rows.append({
            "parameter": name, "family": (
                "nitrogen" if name in NITROGEN else "canopy_scale" if name in CANOPY_SCALE
                else "source_sink" if name in SOURCE_SINK else "water_guard" if name in WATER_GUARD
                else "soil_n_supply" if name in SOIL_N_SUPPLY else "fixed"
            ),
            "status": row["status"], "init": row["init"], "lower": row["lower"], "upper": row["upper"],
            "source": "v37 iteration-3 member137 anchor; v37 q05-q95 + 10% source-range padding",
        })
    proposal = pd.DataFrame(rows)[bounds.columns]
    PROPOSAL.parent.mkdir(parents=True, exist_ok=True)
    PROPOSAL.write_text(proposal.to_csv(index=False), encoding="utf-8")
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(audit_rows).to_csv(AUDIT, index=False)

    design = {
        "schema_version": 1,
        "status": "review_required_not_runnable",
        "design_id": "e02_formal_v38_nitrogen_guarded_200x6_20260829",
        "stage": "S5",
        "purpose": "Conditional formal design after v37 nitrogen multi-arm study; preserves v37 scale while allowing constrained N mechanism and source-sink compensation",
        "anchor": {"run_id": SOURCE_RUN.name, "iteration": 3, "member": 137,
                   "selection_label_policy": "explicit_coordinates_only"},
        "bounds_proposal": str(PROPOSAL.relative_to(ROOT)).replace("\\", "/"),
        "bounds_id_after_approval": "eggplant_e02_v38_nitrogen_guarded_formal_bounds",
        "freeze_required_before_launch": True,
        "active_parameter_count": len(ACTIVE),
        "active_parameter_families": {
            "nitrogen": sorted(NITROGEN), "canopy_scale": sorted(CANOPY_SCALE),
            "source_sink": sorted(SOURCE_SINK), "water_guard": sorted(WATER_GUARD),
            "soil_n_supply": sorted(SOIL_N_SUPPLY),
        },
        "observation_policy": "configs/runs/e02_from_scratch_objective_contract_20260826.csv",
        "group_policy": "configs/runs/e02_group_policy_v36_formal_fresh.csv",
        "nitrogen_response_objective": {
            "enabled": True, "source_variable": "CHFPW", "contrast": "N3_minus_N0_within_same_water",
            "mapping_csv": "configs/runs/e02_from_scratch_water_n_mapping_20260826.csv",
            "weighting": "season_nse", "nse_lambda": 1.0,
            "sst_scope": "season_x_water_stratum", "harvest_scope": "all",
            "terminal_sign": "postrun_hard_gate; no extra whole-family weight inflation",
        },
        "water_response_objective": {
            "enabled": True, "source_variable": "CHFPW", "contrast": "W3_minus_W1_within_same_nitrogen",
            "mapping_csv": "configs/runs/e02_from_scratch_water_n_mapping_20260826.csv",
            "weighting": "season_nse", "nse_lambda": 0.5,
            "sst_scope": "season_x_nitrogen_stratum", "nitrogen_levels": ["N0", "N3"],
        },
        "harvest_fresh_objective": {
            "enabled": True, "mode": "increment_plus_terminal", "variable": "CHFPW",
            "terminal_weighting": "season_rrmse", "rrmse_lambda": 250.0,
        },
        "process_state_objective": {"enabled": True, "mode": "signed_difference_plus_terminal",
                                    "variables": ["LAID", "LWAD", "SWAD"]},
        "seasons": [
            {"season_id": "25SP", "experiment_code": "XXQL2501",
             "bundle_path": "data/user/experiments/xxql2501_formal_armab_rrmse_20260828",
             "role": "calibration", "treatments": [2, 5, 10, 13]},
            {"season_id": "26SP", "experiment_code": "XXQL2601",
             "bundle_path": "data/user/experiments/xxql2601_formal_armab_rrmse_26spncal_20260828",
             "role": "calibration", "treatments": [1, 3, 9, 12]},
        ],
        "diagnostic_only": {"25SP": [3, 4, 9, 11, 12, 14],
                            "26SP": [2, 4, 5, 6, 7, 8, 10, 11]},
        "pest_ies": {"num_reals": 200, "noptmax": 6, "agents": 6, "random_seed": 42,
                     "executable": "official_DSSAT_v4.8"},
        "candidate_gate_order": [
            "25SP both terminal N3-N0 > 0",
            "26SP N_RESPONSE all-event SAE reduction >= 30% versus v37 iteration-3 member137",
            "at least 3 of 4 season-by-water N_RESPONSE NSE layers improve",
            "terminal fresh RRMSE <= 25% each season and abs(PBIAS) <= 15% each season",
            "cumulative fresh NSE >= 0.75 and LAI NSE >= 0.60 each calibration season",
            "non-calibration treatments: fresh/LAI/W_RESPONSE degradation within predeclared tolerances",
            "rank surviving candidates by Phi",
        ],
        "launch_preconditions": [
            "Complete the 25SP N0 nitrogen-supply/input audit and explain why every A-E member retained negative terminal N3-N0.",
            "Correctly rerun C/D/E at N_RESPONSE lambda=1 because the completed historical C/D/E runs were confounded at lambda=2.",
        ],
    }
    CONFIG.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"active={len(ACTIVE)} proposal={PROPOSAL} config={CONFIG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
