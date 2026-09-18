"""Prepare the posterior-informed, yield-rebalanced formal E02 calibration.

The corrected 26SP mineral-N bundle is reused byte-for-byte.  Initial values
come from the previous final posterior median.  Bounds use padded posterior
quantiles with a minimum retained width, while parameters needed to escape the
known low-yield solution keep their previously frozen search envelope.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[2]
PREVIOUS_RUN = ROOT / "workspace/runs/e02_formal_armab_rrmse_26spncal_official_200x6_20260828"
PREVIOUS_CASE = "e02_formal_armab_rrmse_26spncal_200x6_20260828"
SOURCE_BOUNDS_ID = "eggplant_e02_formal_armab_rrmse_widescope_20260828"
BOUNDS_ID = "eggplant_e02_formal_yield_rebalanced_posterior_v1_20260829"
BOUNDS_DIR = ROOT / "data/parameter_registry/bounds_frozen/eggplant"
SOURCE_BOUNDS = BOUNDS_DIR / f"{SOURCE_BOUNDS_ID}.csv"
TARGET_BOUNDS = BOUNDS_DIR / f"{BOUNDS_ID}.csv"
TARGET_BOUNDS_META = BOUNDS_DIR / f"{BOUNDS_ID}.yaml"
SOURCE_CONFIG = ROOT / "configs/runs/e02_formal_armab_rrmse_26spncal_200x6_20260828.json"
GROUP_POLICY = ROOT / "configs/runs/e02_formal_yield_rebalanced_group_policy_20260829.csv"
DESIGN_ID = "e02_formal_yield_rebalanced_post_200x6_20260829"
TARGET_CONFIG = ROOT / f"configs/runs/{DESIGN_ID}.json"
RECEIPT = ROOT / "workspace/reports/e02_formal_yield_rebalanced_post_20260829/preparation_receipt.json"

# These parameters retain the full prior envelope because the previous
# posterior was conditioned on an objective that underweighted yield scale.
ESCAPE_PARAMETERS = {
    "phtmax", "sfdur", "podur", "wtfsd", "porpt", "xfrt", "lfmax",
    "pgeff", "slavr", "slaref", "sizref", "xfint", "pm06", "cmobmx",
    "nrexp", "nrmin", "rtno3", "rtnh4", "nmobmx", "nvsmob", "nrcvr",
    "dswbar", "rwumx", "rtexf", "pormin", "frstmf", "frlff", "swbar_rec",
    "xswfac", "yswfac", "xswbar", "yswbar", "xtrfac", "ytrfac",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _posterior_frames() -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    final_path = PREVIOUS_RUN / f"{PREVIOUS_CASE}.6.par.csv"
    best_path = PREVIOUS_RUN / f"{PREVIOUS_CASE}.5.par.csv"
    if not final_path.is_file() or not best_path.is_file():
        raise FileNotFoundError("previous posterior ensemble is incomplete")
    final = pd.read_csv(final_path)
    if len(final) != 200 or "real_name" not in final:
        raise ValueError(f"unexpected final posterior shape: {final.shape}")
    final.columns = [str(column).lower() for column in final.columns]
    best = pd.read_csv(best_path).set_index("real_name")
    best.index = best.index.astype(str)
    best.columns = [str(column).lower() for column in best.columns]
    best103 = pd.to_numeric(best.loc["103"], errors="coerce")
    return final, final.drop(columns=["real_name"]).median(), best103


def _bounded_interval(center: float, q05: float, q95: float, lower: float, upper: float) -> tuple[float, float]:
    span = upper - lower
    posterior_span = max(q95 - q05, 0.0)
    candidate_lower = q05 - 0.25 * posterior_span
    candidate_upper = q95 + 0.25 * posterior_span
    minimum_width = 0.50 * span
    if candidate_upper - candidate_lower < minimum_width:
        candidate_lower = center - minimum_width / 2.0
        candidate_upper = center + minimum_width / 2.0
    if candidate_lower < lower:
        candidate_upper += lower - candidate_lower
        candidate_lower = lower
    if candidate_upper > upper:
        candidate_lower -= candidate_upper - upper
        candidate_upper = upper
    return max(lower, candidate_lower), min(upper, candidate_upper)


def build_bounds() -> dict:
    if TARGET_BOUNDS.exists() or TARGET_BOUNDS_META.exists():
        raise FileExistsError(f"refusing to overwrite frozen bounds: {TARGET_BOUNDS}")
    bounds = pd.read_csv(SOURCE_BOUNDS)
    bounds["name"] = bounds["name"].astype(str).str.lower()
    posterior, median, best103 = _posterior_frames()
    quantiles = posterior.drop(columns=["real_name"]).quantile([0.05, 0.95])
    audit_rows: list[dict] = []

    for idx, row in bounds.iterrows():
        name = str(row["name"])
        status = str(row.get("status", "active")).lower()
        old_init = float(row["init"])
        old_lower = float(row["lower"])
        old_upper = float(row["upper"])
        if status != "active" or name not in posterior.columns:
            continue

        post_median = float(median[name])
        q05 = float(quantiles.loc[0.05, name])
        q95 = float(quantiles.loc[0.95, name])
        new_lower, new_upper = _bounded_interval(post_median, q05, q95, old_lower, old_upper)
        rule = "posterior_q05_q95_pad25_minwidth50pct"

        if name in ESCAPE_PARAMETERS:
            new_lower, new_upper = old_lower, old_upper
            rule = "full_previous_envelope_for_yield_response_escape"
        elif name.startswith("soil_"):
            # Soil movement was already narrow and measurement-anchored; do
            # not contract it further from one biased posterior.
            new_lower, new_upper = old_lower, old_upper
            rule = "retain_previous_narrow_soil_envelope"

        if name == "soil_slpf":
            new_lower, new_upper = 0.88, 0.93
            post_median = 0.90
            rule = "yield_scale_guard_0.88_0.93"
        elif name == "phtmax":
            # Current evidence does not show a boundary hit: q05=53.18,
            # median=58.69, q95=66.05 under the prior 45-75 envelope.
            new_lower, new_upper = 45.0, 75.0
            rule = "retain_45_75_no_current_boundary_hit"

        margin = max((new_upper - new_lower) * 1.0e-4, 1.0e-8)
        new_init = min(max(post_median, new_lower + margin), new_upper - margin)
        bounds.loc[idx, ["init", "lower", "upper"]] = [new_init, new_lower, new_upper]
        audit_rows.append({
            "name": name,
            "old_init": old_init,
            "posterior_median": float(median[name]),
            "posterior_q05": q05,
            "posterior_q95": q95,
            "best103_iter5": float(best103.get(name, float("nan"))),
            "new_init": new_init,
            "new_lower": new_lower,
            "new_upper": new_upper,
            "rule": rule,
        })

    TARGET_BOUNDS.parent.mkdir(parents=True, exist_ok=True)
    bounds.to_csv(TARGET_BOUNDS, index=False, encoding="utf-8")
    audit = pd.DataFrame(audit_rows)
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    audit_path = RECEIPT.parent / "posterior_bounds_audit.csv"
    audit.to_csv(audit_path, index=False, encoding="utf-8-sig")
    metadata = {
        "bounds_id": BOUNDS_ID,
        "crop": "eggplant",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "frozen_for_formal_calibration",
        "source_bounds_id": SOURCE_BOUNDS_ID,
        "posterior_source": f"{PREVIOUS_CASE}.6.par.csv",
        "initial_value_rule": "final posterior median, except SLPF reset to 0.90",
        "contraction_rule": "q05-q95 padded 25%, minimum 50% previous width",
        "escape_rule": "yield, N-response, water-response and boundary-sensitive parameters retain full previous envelope",
        "phtmax_evidence": {"previous_bounds": [45.0, 75.0], "q05": 53.1811, "median": 58.69065, "q95": 66.05033, "boundary_hit": False},
        "audit_csv": audit_path.relative_to(ROOT).as_posix(),
    }
    TARGET_BOUNDS_META.write_text(yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"active": int((bounds["status"].astype(str).str.lower() == "active").sum()), "audit": audit_path}


def build_config(bounds_info: dict) -> dict:
    if TARGET_CONFIG.exists():
        raise FileExistsError(f"refusing to overwrite config: {TARGET_CONFIG}")
    config = json.loads(SOURCE_CONFIG.read_text(encoding="utf-8"))
    config.update({
        "design_id": DESIGN_ID,
        "purpose": "Posterior-informed formal recalibration with restored terminal-yield scale",
        "bounds_id": BOUNDS_ID,
        "group_policy": GROUP_POLICY.relative_to(ROOT).as_posix(),
        "shared_parameter_scope": "previous full crop pool plus narrow soil movement; posterior-informed bounds with yield-response escape envelopes",
        "initial_condition_policy": "reuse corrected 26SP measured SNH4/SNO3 and sequential measured SH2O bundles without modification",
    })
    config["harvest_dry_objective"].update({
        "terminal_weighting": "season_rrmse",
        "rrmse_lambda": 250.0,
        "acceptance_metric": "RRMSE_pct",
        "acceptance_threshold_pct": 25.0,
        "acceptance_enforcement": "deterministic_postrun_hard_gate",
    })
    config["process_state_objective"].update({
        "balance_note": "BIOMASS_INCREMENT budget 0.30; BIOMASS_TERMINAL budget 0.15; LAI budgets unchanged",
    })
    # First restore overall yield scale.  N response remains at 1/season and
    # water response at 0.5/season so this run does not confound all changes.
    config["nitrogen_response_objective"]["nse_lambda"] = 1.0
    config["water_response_objective"]["nse_lambda"] = 0.5
    config["acceptance"] = {
        "terminal_yield": "hard gate: calibration-treatment dry terminal RRMSE <= 25% in both 25SP and 26SP",
        "terminal_yield_pbias": "abs(PBIAS) <= 15% in both spring seasons",
        "cumulative_dry": "NSE decline <= 0.05 against same-input baseline; 26SP must be positive",
        "lai": "calibration-treatment NSE >= 0.75 in 25SP and >= 0.60 in 26SP",
        "organ_guard": "LWAD/SWAD NSE decline <= 0.10 or RRMSE increase <= 15%",
        "candidate_rule": "scan all iterations; reject any candidate failing a hard gate before Phi ranking",
    }
    config["pest_ies"] = {
        "num_reals": 200,
        "noptmax": 6,
        "agents": 6,
        "random_seed": 43,
        "initial_ensemble_method": "lhs",
    }
    TARGET_CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return config


def main() -> int:
    if not GROUP_POLICY.is_file():
        raise FileNotFoundError(GROUP_POLICY)
    bounds_info = build_bounds()
    config = build_config(bounds_info)
    bundle_hashes = {}
    for season in config["seasons"]:
        bundle = ROOT / season["bundle_path"]
        manifest = bundle / "input_manifest.json"
        actual = sha256(manifest)
        if actual != season["bundle_manifest_sha256"]:
            raise ValueError(f"bundle manifest hash mismatch: {season['season_id']}")
        bundle_hashes[season["season_id"]] = actual

    receipt = {
        "schema_version": 1,
        "design_id": DESIGN_ID,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "config": TARGET_CONFIG.relative_to(ROOT).as_posix(),
        "config_sha256": sha256(TARGET_CONFIG),
        "bounds_id": BOUNDS_ID,
        "bounds_sha256": sha256(TARGET_BOUNDS),
        "group_policy": GROUP_POLICY.relative_to(ROOT).as_posix(),
        "group_policy_sha256": sha256(GROUP_POLICY),
        "posterior_source": (PREVIOUS_RUN / f"{PREVIOUS_CASE}.6.par.csv").relative_to(ROOT).as_posix(),
        "posterior_rows": 200,
        "active_parameters": bounds_info["active"],
        "terminal_rrmse_lambda_per_season": 250.0,
        "biomass_increment_budget": 0.30,
        "biomass_terminal_budget": 0.15,
        "bundle_manifest_sha256": bundle_hashes,
    }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
