"""Build the N_RESPONSE + SOIL_WATER weight-reduced (1/3) six-treatment case.

Derives from the completed ``e02_v2_formal25sp_nreleased_nrexp_nrmin_6treat_150x4_20260805_corrected``
run by copying its entire directory, renaming the PST/contract to a new prefix,
rebuilding the T8 weights audit from the observation registry, and re-applying
the T8 §7.2 weight formula with a group policy in which N_RESPONSE and
SOIL_WATER phi_budgets are divided by 9 (so per-observation weights become
1/3 of the original, since weight is proportional to sqrt(budget)).

Everything else (parameter set, observations, FileX/FileT, custom executable)
is inherited unchanged from the source run.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pandas as pd
import pyemu

ROOT = Path(r"D:/Tomato_Cal")
SOURCE_DIR = ROOT / "workspace/runs/e02_v2_formal25sp_nreleased_nrexp_nrmin_6treat_150x4_20260805_corrected"
SOURCE_PREFIX = SOURCE_DIR.name
TARGET_PREFIX = "e02_v2_formal25sp_nreleased_nrexp_nrmin_6treat_150x4_20260806_nresp_sw_onethird_20260806"
TARGET_DIR = ROOT / "workspace/runs" / TARGET_PREFIX
GROUP_POLICY = "configs/runs/t10_water_n_response_group_policy_nresp_sw_onethird_20260806.csv"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _rename_files() -> None:
    """Rename all source-prefixed files to the target prefix in the new dir."""
    for path in TARGET_DIR.iterdir():
        if path.is_file() and SOURCE_PREFIX in path.name:
            new_name = path.name.replace(SOURCE_PREFIX, TARGET_PREFIX)
            path.rename(TARGET_DIR / new_name)


def _rewrite_text(prefix_old: str, prefix_new: str) -> None:
    """Replace the old prefix string inside all text artifacts."""
    binary_exts = {".png", ".pdf", ".svg"}
    for path in TARGET_DIR.rglob("*"):
        if not path.is_file() or path.suffix.lower() in binary_exts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if prefix_old in text:
            path.write_text(text.replace(prefix_old, prefix_new), encoding="utf-8")


def _build_weights_audit() -> Path:
    """Reconstruct <prefix>.weights.audit.csv from the observation registry.

    The T8 weight applicator (``_apply_t8_weights``) reads obsnme, obgnme,
    sigma, and weight columns from the audit CSV.  The observation registry
    already carries every column it needs (plus provenance fields).
    """
    registry_path = next(TARGET_DIR.glob("*_observation_registry.csv"))
    registry = pd.read_csv(registry_path, encoding="utf-8-sig")
    audit_cols = [
        "obsnme", "obgnme", "raw_obsval", "obsval", "raw_sigma", "sigma",
        "sigma_source", "base_weight", "group_multiplier", "weight",
        "transform", "transform_offset", "transform_reference",
        "sim_token", "model_output_file", "weight_policy_id", "phi_role",
    ]
    audit = registry.reindex(columns=audit_cols)
    audit_path = TARGET_DIR / f"{TARGET_PREFIX}.weights.audit.csv"
    audit.to_csv(audit_path, index=False, encoding="utf-8-sig")
    return audit_path


def _group_multipliers(n_obs_by_family: dict, budgets: dict) -> dict:
    return {f: (budgets[f] / max(n_obs_by_family[f], 1)) ** 0.5 for f in budgets}


def main() -> None:
    if TARGET_DIR.exists():
        raise FileExistsError(f"target already exists: {TARGET_DIR}")
    if not SOURCE_DIR.is_dir() or not (SOURCE_DIR / f"{SOURCE_PREFIX}.pst").is_file():
        raise FileNotFoundError(f"source run incomplete: {SOURCE_DIR}")

    # Copy ONLY build artifacts (PST, ins, params, tpl, design, registry, ensemble,
    # transforms, DSSBatch).  Exclude all PEST++ run RESULTS so the new directory
    # is a clean unbuilt case — otherwise PEST++ may treat the inherited .rec /
    # .par.csv / .phi.* / calibration_finalize as a completed run and skip execution.
    result_patterns = shutil.ignore_patterns(
        "*.rec", "*.rmr", "*.log", "*.phi.*", "*.pcs.csv", "*.pdc.csv",
        "*.base.par", "*.base.rei", "*.obs.csv", "*.par.csv",
        "*.adjusted.obs_data.csv", "*.adjusted.weights.csv",
        "*.obs+noise.csv", "*.weights.csv",
        "run_status.json", "formal_launch_receipt.json",
        "custom_nresp_calibration.*.log",
        "calibration_finalize", "_agents", "_seasons", "best_member*",
        "ies_quality", "manager", "*.pid",
        "multiseason_run_status.json", "PestEval.OUT", "PestHarvest.OUT",
        "PestJoint.OUT", "PestTmtGrow.OUT", "PestNResponse.OUT", "PestSoilWat.OUT",
        "diagnostic_figures", "*.png",
        "filex_water_n_mapping_runtime_audit.csv",
        "weight_adjustment_manifest.json",
    )
    print(f"[1/5] copying build artifacts {SOURCE_DIR.name} -> {TARGET_PREFIX}/")
    shutil.copytree(SOURCE_DIR, TARGET_DIR, ignore=result_patterns)

    print("[2/5] renaming files to target prefix")
    _rename_files()
    print("[3/5] rewriting prefix references inside artifacts")
    _rewrite_text(SOURCE_PREFIX, TARGET_PREFIX)

    print("[4/5] building weights.audit.csv from observation registry")
    audit_path = _build_weights_audit()

    # Load run mapping for the season bucketing inside _apply_t8_weights.
    run_mapping_path = TARGET_DIR / f"{TARGET_PREFIX}_run_mapping.csv"
    run_mapping_rows = pd.read_csv(run_mapping_path).to_dict("records")

    print("[5/5] re-applying T8 weights with reduced N_RESPONSE/SOIL_WATER budgets")
    sys.path.insert(0, str(ROOT))
    from src.calibration.build_pest_multiseason import _apply_t8_weights, _load_group_budgets

    _apply_t8_weights(TARGET_DIR, TARGET_PREFIX, GROUP_POLICY, run_mapping_rows)

    # ---- Verify and summarise the weight change ----
    pst = pyemu.Pst(str(TARGET_DIR / f"{TARGET_PREFIX}.pst"))
    obs = pst.observation_data.copy()
    audit = pd.read_csv(audit_path, encoding="utf-8-sig")

    # Family map mirrors _family_for_group in build_pest_multiseason.
    def family_of(obgnme: str) -> str:
        g = str(obgnme).upper()
        if g.startswith("25SP_"):
            g = g[5:]
        if g.startswith("NRESP") or g.startswith("NRESPS"):
            return "N_RESPONSE"
        if g.startswith("SW") and not g.startswith("SWA"):
            return "SOIL_WATER"
        if g.startswith("LAID") or g.startswith("LAIX"):
            return "CANOPY"
        if g.startswith("LWAD") or g.startswith("SWAD"):
            return "BIOMASS"
        if g.startswith("CHPDT") or g.startswith("HPODW"):
            return "HARVEST_DRY"
        if g.startswith("CHFPW"):
            return "HARVEST_FRESH"
        if g.startswith("SNAM") or g.startswith("LNAM"):
            return "PLANT_N"
        return "OTHER"

    audit["family"] = audit["obgnme"].map(family_of)
    new_budgets = _load_group_budgets(GROUP_POLICY)
    old_budgets = _load_group_budgets(
        "configs/runs/t10_water_n_response_group_policy_harvestdry250_v1.csv"
    )
    summary = []
    for fam in ["N_RESPONSE", "SOIL_WATER", "CANOPY", "BIOMASS", "HARVEST_DRY"]:
        n = int((audit["family"].eq(fam) & audit["weight"].gt(0)).sum())
        old_m = (old_budgets.get(fam, 0) / max(n, 1)) ** 0.5 if fam in old_budgets else 0.0
        new_m = (new_budgets.get(fam, 0) / max(n, 1)) ** 0.5 if fam in new_budgets else 0.0
        ratio = new_m / old_m if old_m else 0.0
        summary.append({
            "family": fam, "n_active_obs": n,
            "old_phi_budget": old_budgets.get(fam, 0),
            "new_phi_budget": new_budgets.get(fam, 0),
            "old_multiplier": round(old_m, 6),
            "new_multiplier": round(new_m, 6),
            "weight_ratio": round(ratio, 4),
        })

    n_active = int((obs["weight"].astype(float) > 0).sum())
    manifest = {
        "source_run": str(SOURCE_DIR),
        "target_run": str(TARGET_DIR),
        "group_policy": GROUP_POLICY,
        "weight_adjustment": "N_RESPONSE and SOIL_WATER weights reduced to 1/3 "
        "(phi_budget divided by 9; weight ~ sqrt(budget))",
        "n_parameters": int(pst.npar),
        "n_parameters_adjustable": int(pst.npar_adj),
        "n_observations": int(pst.nobs),
        "n_active_observations": n_active,
        "n_reals": 150,
        "noptmax": 4,
        "custom_executable": str(ROOT / "windows/windows_nresp_20260803/dscsm048_nresp.exe"),
        "source_pst_sha256": _sha256(SOURCE_DIR / f"{SOURCE_PREFIX}.pst"),
        "family_weight_summary": summary,
    }
    manifest_path = TARGET_DIR / "weight_adjustment_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(json.dumps({
        "target": TARGET_PREFIX,
        "npar": int(pst.npar),
        "npar_adj": int(pst.npar_adj),
        "nobs": int(pst.nobs),
        "n_active": n_active,
        "weight_summary": summary,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
