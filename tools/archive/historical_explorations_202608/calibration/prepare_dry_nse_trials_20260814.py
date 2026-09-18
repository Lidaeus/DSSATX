"""Prepare three small, auditable A/B/C dry-yield calibration controls."""
from __future__ import annotations
import argparse, json, shutil, sys
from pathlib import Path
import numpy as np
import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
BASE = "e02_v2_fixedsoil_joint_official_25sp26sp_200x5_20260814"

def replace_tree(root: Path, old: str, new: str) -> None:
    for p in sorted(root.rglob("*"), key=lambda x: len(str(x)), reverse=True):
        if p.is_file():
            try:
                b = p.read_bytes()
                if old.encode() in b:
                    p.write_bytes(b.replace(old.encode(), new.encode()))
            except OSError:
                pass
        if p.name != p.name.replace(old, new):
            p.rename(p.with_name(p.name.replace(old, new)))

def set_raw_nse(pst, run: Path, prefix: str) -> dict:
    reg_path = run / f"{prefix}_observation_registry.csv"
    reg = pd.read_csv(reg_path, encoding="utf-8-sig")
    # PST instruction names use the DSSAT simulation token (CHPDTS), while
    # the registry's group-oriented names use CHPDTM; normalize that alias.
    key = reg["obsnme"].astype(str).str.upper().str.replace("CHPDTM", "CHPDTS", regex=False)
    reg.index = key
    obs = pst.observation_data
    names = [n for n in obs.index if "CHPDTS" in str(n).upper()
             and "CHFPWS" not in str(n).upper()]
    # Include both intermediate and terminal cumulative dry observations.
    names = [n for n in names if str(n).upper() in reg.index]
    by_season = {}
    for n in names:
        r = reg.loc[str(n).upper()]
        by_season.setdefault(str(r.season_id), []).append(n)
    budget = 0.75
    audit_path = run / f"{prefix}.weights.audit.csv"
    audit = pd.read_csv(audit_path, encoding="utf-8-sig")
    audit.index = audit["obsnme"].astype(str).str.upper()
    result = {}
    for season, ns in by_season.items():
        vals = np.array([float(reg.loc[str(n).upper(), "raw_obsval"]) for n in ns])
        mean = float(vals.mean())
        sst = float(((vals - mean) ** 2).sum())
        if sst <= 0:
            raise ValueError(f"non-positive dry-yield SST for {season}")
        sigma = float(np.sqrt(sst / len(ns)))
        weight = float(np.sqrt(budget / sst))
        for n in ns:
            k = str(n).upper()
            val = float(reg.loc[k, "raw_obsval"])
            obs.loc[n, "obsval"] = val
            obs.loc[n, "weight"] = weight
            obs.loc[n, "obgnme"] = "DRYNSE"
            reg.loc[k, "obsval"] = val; reg.loc[k, "weight"] = weight
            reg.loc[k, "sigma"] = sigma; reg.loc[k, "sigma_source"] = "nse_sst_normalized"
            reg.loc[k, "group_multiplier"] = 1.0; reg.loc[k, "transform"] = "raw"
            if k in audit.index:
                audit.loc[k, "obsval"] = val; audit.loc[k, "weight"] = weight
                audit.loc[k, "sigma"] = sigma; audit.loc[k, "sigma_source"] = "nse_sst_normalized"
                audit.loc[k, "group_multiplier"] = 1.0; audit.loc[k, "obgnme"] = "DRYNSE"
        result[season] = {"n": len(ns), "sst": sst, "sigma": sigma, "weight": weight,
                          "expected_phi_budget": budget}
    reg.reset_index(drop=True).to_csv(reg_path, index=False, encoding="utf-8-sig")
    audit.reset_index(drop=True).to_csv(audit_path, index=False, encoding="utf-8-sig")
    return result

def prepare(base_dir: Path, out_dir: Path, trial: str, raw_nse: bool, release: bool) -> None:
    if out_dir.exists(): raise FileExistsError(out_dir)
    shutil.copytree(base_dir, out_dir)
    replace_tree(out_dir, BASE, out_dir.name)
    prefix = out_dir.name
    pst_path = out_dir / f"{prefix}.pst"
    pst = pyemu.Pst(str(pst_path))
    pst.control_data.noptmax = 3
    pst.pestpp_options["ies_num_reals"] = 80
    pst.pestpp_options["ies_parameter_ensemble"] = f"{prefix}.0.par.csv"
    pst.pestpp_options["ies_observation_ensemble"] = f"{prefix}.observation_ensemble.csv"
    pst.pestpp_options["ies_include_base" ] = "false"
    if release:
        for p, lo, hi in [("phtmax", None, 75.0), ("podur", 25.0, None)]:
            if p in pst.parameter_data.index:
                if lo is not None: pst.parameter_data.loc[p, "parlbnd"] = lo
                if hi is not None: pst.parameter_data.loc[p, "parubnd"] = hi
    target_audit = set_raw_nse(pst, out_dir, prefix) if raw_nse else None
    pst.write(str(pst_path))
    from src.calibration.build_pest import _write_observation_noise_ensemble
    _write_observation_noise_ensemble(pst_path, out_dir / f"{prefix}.weights.audit.csv", out_dir, prefix, 80, 20260814 + ord(trial))
    from src.calibration.initial_ensemble import generate_lhs_ensemble, write_ensemble_csv
    par = pst.parameter_data
    bounds = pd.DataFrame({"name": par.index, "init": par.parval1, "lower": par.parlbnd,
                           "upper": par.parubnd, "status": np.where(par.partrans == "fixed", "fixed", "active")})
    ens = generate_lhs_ensemble(80, bounds, 20260814 + ord(trial), method="sobol")
    write_ensemble_csv(ens, out_dir / f"{prefix}.0.par.csv")
    manifest = {"trial": trial, "baseline": BASE, "raw_dry_nse": raw_nse, "released_production_bounds": release,
                "noptmax": 3, "ies_num_reals": 80, "dry_nse_budget_per_season": 0.75,
                "dry_nse_audit": target_audit, "parameters_released": {"PHTMAX_upper": 75.0, "PODUR_lower": 25.0} if release else {}}
    (out_dir / "trial_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--base", default=str(ROOT / "workspace/runs" / BASE)); ap.add_argument("--out-root", default=str(ROOT / "workspace/runs")); args = ap.parse_args()
    base = Path(args.base); root = Path(args.out_root)
    specs = [("A", True, False), ("B", False, True), ("C", True, True)]
    for t, raw, rel in specs:
        name = f"{BASE}_control{t}_80x3_20260814"
        prepare(base, root / name, t, raw, rel)
        print(name)
if __name__ == "__main__": main()
