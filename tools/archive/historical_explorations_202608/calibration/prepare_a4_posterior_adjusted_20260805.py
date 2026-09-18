"""Prepare A4 posterior-edge-adjusted bounds and a fresh calibration case.

The A4 v1 observation/weight contract is retained byte-for-byte in scope;
only bounds with material final-posterior edge pressure are released modestly.
Hard/structural limits (for example PPSEN's zero floor and NUPAV's unit ceiling)
remain unchanged.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common.param_registry import PHYSICAL_BOUNDS

ROOT = Path(r"D:/Tomato_Cal")
SOURCE_ID = "a4_v1_formal25sp_nreleased_nrexp_nrmin_nup_6treat_150x4_20260804"
SOURCE_RUN = ROOT / "workspace/runs" / SOURCE_ID
NEW_ID = "a4_v2_posterior_adjusted_25sp_nreleased_nrexp_nrmin_nup_6treat_150x4_20260805"
TARGET_RUN = ROOT / "workspace/runs" / NEW_ID
SOURCE_BOUNDS = ROOT / "data/parameter_registry/bounds_frozen/eggplant" / f"{SOURCE_ID}.csv"
POSTERIOR = SOURCE_RUN / f"{SOURCE_ID}.4.par.csv"
PROPOSAL = ROOT / "data/parameter_registry/bounds_proposals/eggplant" / f"{NEW_ID}.csv"
AUDIT = ROOT / "data/parameter_registry/bounds_proposals/eggplant" / f"{NEW_ID}_posterior_edge_audit.csv"

# Modest releases selected from >=10% posterior mass in a 2%-of-prior-span
# boundary band. Values preserve known DSSAT/physiological ordering constraints.
UPDATES: dict[str, tuple[float, float, str]] = {
    "SLAVR": (280.0, 330.0, "upper-edge pressure; release SLAVR ceiling modestly"),
    "XMAGE": (13.0, 18.0, "upper-edge pressure; release XMAGE ceiling modestly"),
    "SOIL_SSAT_06": (0.3180, 0.3420, "upper-edge pressure; release soil SSAT06 modestly"),
    "SOIL_SSAT_08": (0.3030, 0.3290, "upper-edge pressure; release soil SSAT08 modestly"),
    "PORPT": (0.15, 0.30, "upper-edge pressure; release PORPT ceiling modestly"),
    "SOIL_SLPF": (0.90, 0.97, "upper-edge pressure; release soil SLPF ceiling modestly"),
    "SOIL_SDUL_02": (0.2970, 0.3150, "upper-edge pressure; release soil SDUL02 ceiling modestly"),
    "XFINT": (0.12, 0.50, "upper-edge pressure; use project XFINT ceiling 0.50"),
    "EM-FL": (22.0, 35.0, "upper-edge pressure; release EM-FL ceiling modestly"),
    "XFRT": (0.70, 1.00, "upper-edge pressure; release XFRT to physical ceiling"),
    "SIZREF": (240.0, 360.0, "upper-edge pressure; release SIZREF ceiling modestly"),
    "NMOBMX": (0.0, 0.40, "lower-edge pressure; release NMOBMX to physical floor"),
    "LFMAX": (1.15, 1.36, "lower-edge pressure; release LFMAX floor modestly"),
    "FL-SD": (5.0, 21.0, "lower-edge pressure; release FL-SD floor modestly"),
    "LNGSH": (24.0, 48.8, "lower-edge pressure; release LNGSH floor modestly"),
    "TB1": (7.50, 10.0, "lower-edge pressure; release TB1 while preserving TB1 < TO11"),
    "SIZLF": (280.0, 350.0, "lower-edge pressure; release SIZLF floor modestly"),
    "PODUR": (25.0, 58.0, "lower-edge pressure; release PODUR floor modestly"),
    "TO12": (18.5, 27.5, "lower-edge pressure; release TO12 while preserving TO12 < TO22"),
    "RHGHT": (0.50, 1.20, "lower-edge pressure; release RHGHT floor modestly"),
    "SDPDV": (100.0, 230.900885, "lower-edge pressure; release SDPDV floor modestly"),
    "TO22": (28.0, 29.5136955, "lower-edge pressure; release TO22 floor while preserving TO12 < TO22"),
    "NRCVR": (0.0, 0.35, "lower-edge pressure; release NRCVR to physical floor"),
    "TB2": (7.50, 12.0, "lower-edge pressure; release TB2 floor modestly"),
    "SENDAY": (0.0, 0.08, "lower-edge pressure; release SENDAY to physical floor"),
    "NUPQ": (0.25, 1.50, "lower-edge pressure; release NUPQ floor for A4 curve shape"),
    "FRSTMF": (0.40, 0.6681043225, "lower-edge pressure; release FRSTMF floor modestly"),
    "SOIL_SLLL_02": (0.1500, 0.1620, "lower-edge pressure; release soil SLLL02 modestly"),
    "SOIL_SBDM_04": (1.45, 1.56, "lower-edge pressure; release soil SBDM04 modestly"),
    "SOIL_SDUL_06": (0.2800, 0.3020, "lower-edge pressure; release soil SDUL06 modestly"),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy_contract_files() -> None:
    if TARGET_RUN.exists():
        raise FileExistsError(TARGET_RUN)
    TARGET_RUN.mkdir(parents=True)
    for path in SOURCE_RUN.iterdir():
        if not path.is_file():
            continue
        name = path.name
        if (
            name.endswith(".OUT.ins")
            or name in {
                "DSSBatch.six_treatment.v48",
                f"{SOURCE_ID}.observation_ensemble.csv",
                f"{SOURCE_ID}.observation_transforms.json",
                "six_treatment_design.json",
            }
            or name.endswith("_observation_registry.csv")
            or name.endswith("_run_mapping.csv")
            or name == f"{SOURCE_ID}_params.csv"
            or name == f"{SOURCE_ID}_params.csv.tpl"
        ):
            shutil.copy2(path, TARGET_RUN / name.replace(SOURCE_ID, NEW_ID))


def main() -> int:
    _copy_contract_files()
    source_pst = SOURCE_RUN / f"{SOURCE_ID}.pst"
    pst = pyemu.Pst(str(source_pst))
    new_param = f"{NEW_ID}_params.csv"
    new_tpl = f"{NEW_ID}_params.csv.tpl"
    new_pst = TARGET_RUN / f"{NEW_ID}.pst"
    pst.parameter_data.index = pst.parameter_data.index.astype(str).str.lower()
    bounds = pd.read_csv(SOURCE_BOUNDS, encoding="utf-8-sig")
    posterior = pd.read_csv(POSTERIOR)
    col_map = {str(c).upper(): c for c in posterior.columns if str(c).lower() not in {"real_name", "realization"}}
    prior = bounds.copy()
    audit_rows = []
    changed = 0
    for idx, row in bounds.iterrows():
        name = str(row["name"]).upper()
        if name not in col_map:
            continue
        values = pd.to_numeric(posterior[col_map[name]], errors="coerce").dropna().to_numpy(float)
        old_lo, old_hi = float(row["lower"]), float(row["upper"])
        span = old_hi - old_lo
        tol = max(span * 0.02, 1e-12)
        q01, q05, q50, q95, q99 = (float(np.quantile(values, q)) for q in (0.01, .05, .50, .95, .99))
        frac_lo = float(np.mean(values <= old_lo + tol))
        frac_hi = float(np.mean(values >= old_hi - tol))
        edge = frac_lo >= 0.10 or frac_hi >= 0.10
        new_lo, new_hi = old_lo, old_hi
        decision = "unchanged_no_material_edge_pressure"
        note = str(row.get("review_note", ""))
        is_fixed = str(row.get("status", "")).lower() == "fixed"
        if is_fixed:
            audit_rows.append({
                "name": name, "prior_lower": old_lo, "prior_upper": old_hi,
                "proposed_lower": old_lo, "proposed_upper": old_hi,
                "q01": q01, "q05": q05, "q50": q50, "q95": q95, "q99": q99,
                "posterior_min": float(values.min()), "posterior_max": float(values.max()),
                "frac_lower_2pct": frac_lo, "frac_upper_2pct": frac_hi,
                "edge_pressure": False, "decision": "fixed_unchanged", "note": "fixed parameter",
            })
            continue
        if name in UPDATES:
            new_lo, new_hi, note = UPDATES[name]
            decision = "released_by_posterior_edge"
            changed += 1
        elif edge:
            decision = "retained_hard_or_structural_limit"
            note = "edge pressure retained: physical or structural constraint requires current bound"
        if name in PHYSICAL_BOUNDS:
            phys_lo, phys_hi = PHYSICAL_BOUNDS[name]
            new_lo, new_hi = max(new_lo, phys_lo), min(new_hi, phys_hi)
        if not new_lo < new_hi:
            raise RuntimeError(f"invalid proposed range for {name}: {new_lo}, {new_hi}")
        if not new_lo <= float(row["init"]) <= new_hi:
            raise RuntimeError(f"init outside proposed range for {name}: {row['init']} not in {new_lo}-{new_hi}")
        prior.loc[idx, "lower"], prior.loc[idx, "upper"] = new_lo, new_hi
        if name in pst.parameter_data.index:
            pst.parameter_data.loc[name, "parlbnd"] = new_lo
            pst.parameter_data.loc[name, "parubnd"] = new_hi
        audit_rows.append({
            "name": name, "prior_lower": old_lo, "prior_upper": old_hi,
            "proposed_lower": new_lo, "proposed_upper": new_hi,
            "q01": q01, "q05": q05, "q50": q50, "q95": q95, "q99": q99,
            "posterior_min": float(values.min()), "posterior_max": float(values.max()),
            "frac_lower_2pct": frac_lo, "frac_upper_2pct": frac_hi,
            "edge_pressure": edge, "decision": decision, "note": note,
        })

    # Explicit project invariants.
    fl = prior[prior["name"].astype(str).str.upper().eq("FL-VS")].iloc[0]
    if str(fl["status"]).lower() != "fixed" or float(fl["init"]) != 100.0:
        raise RuntimeError("FL-VS must remain fixed at the A4 v1 value 100")
    if prior[(prior["status"].astype(str).str.lower().eq("active")) & prior["location"].astype(str).str.upper().isin({"SOIL", "IC", "INIT"})].shape[0] == 0:
        raise RuntimeError("expected active A4 soil parameters were unexpectedly removed")
    prior.to_csv(PROPOSAL, index=False, encoding="utf-8-sig")
    pd.DataFrame(audit_rows).to_csv(AUDIT, index=False, encoding="utf-8-sig")

    # Rename model I/O contract to the new case and preserve E02/A4 settings.
    rename = {str(x): str(x).replace(SOURCE_ID, NEW_ID) for x in pst.instruction_files}
    pst.model_output_data.index = [rename.get(str(x), str(x)) for x in pst.model_output_data.index]
    pst.model_output_data["pest_file"] = [rename.get(str(x), str(x)) for x in pst.model_output_data["pest_file"]]
    pst.model_input_data.index = [new_tpl]
    pst.model_input_data.loc[new_tpl, "pest_file"] = new_tpl
    pst.model_input_data.loc[new_tpl, "model_file"] = new_param
    pst.pestpp_options["ies_observation_ensemble"] = f"{NEW_ID}.observation_ensemble.csv"
    pst.pestpp_options["ies_num_reals"] = "150"
    pst.pestpp_options["rand_seed"] = "20260803"
    pst.control_data.noptmax = 4
    design = json.loads((TARGET_RUN / "six_treatment_design.json").read_text(encoding="utf-8"))
    design["design_id"] = NEW_ID
    design["bounds_id"] = NEW_ID
    design["custom_dssat_executable"] = str((ROOT / "windows/windows_a4_20260804/dscsm048_a4.exe").resolve())
    design["custom_spe"] = str((ROOT / "windows/windows_a4_20260804/Genotype/TMGRO048.SPE").resolve())
    (TARGET_RUN / "six_treatment_design.json").write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    transform_name = f"{NEW_ID}.observation_transforms.json"
    pst.model_command = (
        f'python "{(ROOT / "src/calibration/run_multiseason.py").as_posix()}" '
        f'--design "{(TARGET_RUN / "six_treatment_design.json").as_posix()}" '
        f"--param-csv {new_param} --harvest-var CHPDT --keep-nitrogen-outputs "
        f"--prefix {NEW_ID} --observation-transform-config {transform_name}"
    )
    pst.write(str(new_pst))
    check = pyemu.Pst(str(new_pst))
    if check.npar != 111 or check.npar_adj != 104 or check.nobs != 434:
        raise RuntimeError(f"contract changed unexpectedly: npar={check.npar}, npar_adj={check.npar_adj}, nobs={check.nobs}")
    manifest = {
        "source_run": str(SOURCE_RUN.resolve()), "target_run": str(TARGET_RUN.resolve()),
        "source_bounds": str(SOURCE_BOUNDS.resolve()), "bounds_proposal": str(PROPOSAL.resolve()),
        "posterior_source": str(POSTERIOR.resolve()), "posterior_edge_audit": str(AUDIT.resolve()),
        "changed_parameter_count": changed, "parameter_count": {"total": int(check.npar), "adjustable": int(check.npar_adj)},
        "observation_count": int(check.nobs), "active_observation_count": int((check.observation_data["weight"] > 0).sum()),
        "n_reals": 150, "noptmax": 4, "rand_seed": 20260803,
        "custom_executable": str((ROOT / "windows/windows_a4_20260804/dscsm048_a4.exe").resolve()),
        "custom_executable_sha256": _sha256(ROOT / "windows/windows_a4_20260804/dscsm048_a4.exe"),
        "custom_spe": str((ROOT / "windows/windows_a4_20260804/Genotype/TMGRO048.SPE").resolve()),
        "custom_spe_sha256": _sha256(ROOT / "windows/windows_a4_20260804/Genotype/TMGRO048.SPE"),
        "decision_rule": "release only explicitly reviewed parameters with >=10% posterior mass in 2%-span edge band; retain hard/structural limits",
    }
    (TARGET_RUN / "a4_v2_case_build_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(pd.DataFrame(audit_rows).query("decision == 'released_by_posterior_edge'")[['name','prior_lower','prior_upper','proposed_lower','proposed_upper','frac_lower_2pct','frac_upper_2pct']].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
