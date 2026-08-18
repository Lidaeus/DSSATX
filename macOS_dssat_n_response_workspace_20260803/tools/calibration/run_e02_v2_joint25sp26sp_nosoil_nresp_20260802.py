"""Build, audit and optionally execute the 25SP+26SP E02 V2 calibration.

The run inherits the 99 active bounds from the 25SP nreleased V2 batch,
keeps organ-N parameters active, and removes SOIL_WATER/NRESP from Phi.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
SOURCE_DESIGN = ROOT / "configs/runs/eggplant_e02_v2_joint25sp26sp_nosoil_nresp_20260802.json"
POLICY = ROOT / "configs/runs/e02_v2_joint25sp26sp_nosoil_nresp_policy_20260802.csv"
BOUNDS_ID = "eggplant_e02_v2_formal25sp_nreleased_20260802"


def run(cmd: list[str]) -> None:
    print("+", subprocess.list2cmdline(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def audit_observation_contract(out: Path, case: str, expected_params: int) -> dict:
    registry_path = out / f"{case}_observation_registry.csv"
    mapping_path = out / f"{case}_run_mapping.csv"
    weights_path = out / f"{case}.weights.audit.csv"
    registry = pd.read_csv(registry_path, encoding="utf-8-sig")
    mapping = pd.read_csv(mapping_path, encoding="utf-8-sig")
    weights = pd.read_csv(weights_path, encoding="utf-8-sig")
    active = registry[pd.to_numeric(registry["weight"], errors="coerce") > 0].copy()
    if registry["obsnme"].duplicated().any():
        raise RuntimeError("duplicate observation names in registry")
    if len(weights) != len(registry) or set(weights["obsnme"]) != set(registry["obsnme"]):
        raise RuntimeError("weights audit and observation registry are not one-to-one")
    seasons = set(active["season_id"].astype(str))
    if seasons != {"25SP", "26SP"}:
        raise RuntimeError(f"unexpected active seasons: {seasons}")
    groups = active["obgnme"].astype(str)
    # Soil-water tokens are SW followed by a numeric layer/observation id;
    # SWADM is stem dry mass and must remain in the BIOMASS family.
    soil_active = int(groups.str.contains(r"SOIL_WATER|^(?:25SP|26SP)_SW\d+M", case=False, regex=True).sum())
    nresp_active = int(groups.str.contains("NRESP", case=False, regex=True).sum())
    if soil_active or nresp_active:
        raise RuntimeError(f"excluded groups active: soil={soil_active}, nresp={nresp_active}")
    if int(expected_params) != int(pyemu.Pst(str(out / f"{case}.pst")).npar_adj):
        raise RuntimeError("adjustable parameter count differs from frozen contract")
    if not mapping["global_run"].is_unique:
        raise RuntimeError("global run mapping is not unique")
    run_lookup = mapping.set_index("global_run")
    extracted = registry["obsnme"].astype(str).str.extract(r"_R(?P<global_run>\d+)(?:_|$)")
    registry_run = pd.to_numeric(extracted["global_run"], errors="coerce")
    if registry_run.isna().any() or not registry_run.isin(run_lookup.index).all():
        raise RuntimeError("observation names contain unknown global run numbers")
    check = registry.copy()
    check["_global_run"] = registry_run.astype(int)
    joined = check.merge(run_lookup.reset_index(), left_on="_global_run", right_on="global_run", suffixes=("", "_map"), validate="many_to_one")
    if (joined["season_id"].astype(str) != joined["season_id_map"].astype(str)).any():
        raise RuntimeError("observation season does not match run mapping")
    if pd.to_numeric(joined["treatment"], errors="coerce").ne(pd.to_numeric(joined["treatment_map"], errors="coerce")).any():
        raise RuntimeError("observation treatment does not match run mapping")
    # Every registry observation must have exactly one instruction-file token;
    # this catches a silent sim/obs row-order or output-file mismatch.
    ins_names = set()
    for ins_path in out.glob(f"{case}_*.ins"):
        text = ins_path.read_text(encoding="utf-8", errors="replace")
        ins_names.update(re.findall(r"!([^!]+)!", text))
    registry_names = set(registry["obsnme"].astype(str))
    missing_ins = sorted(registry_names - ins_names)
    extra_ins = sorted(ins_names - registry_names)
    if missing_ins or extra_ins:
        raise RuntimeError(
            f"instruction/registry mismatch: missing={missing_ins[:5]}, extra={extra_ins[:5]}"
        )
    # T8 fairness audit: for every active season-family bucket, the exact
    # weighted residual variance budget must equal the declared budget.
    active["_family"] = active["obgnme"].astype(str).str.upper()
    active["_family"] = active["_family"].str.replace(r"^(25SP|26SP)_", "", regex=True)
    active["_family"] = active["_family"].str.replace(r"(_H\d+|_D\d+)$", "", regex=True)
    family_map = {"LAIDM": "CANOPY", "LAIXM": "CANOPY", "LWADM": "BIOMASS", "SWADM": "BIOMASS", "SNAMM": "PLANT_N", "LNAMM": "PLANT_N", "CHPDTM": "HARVEST_DRY", "HPODWM": "HARVEST_DRY"}
    active["_family"] = active["_family"].map(lambda x: next((v for k, v in family_map.items() if x.startswith(k)), x))
    active["weighted_variance"] = (pd.to_numeric(active["weight"]) * pd.to_numeric(active["sigma"])) ** 2
    budget_rows = pd.read_csv(ROOT / "configs/runs/t10_v2_joint25sp26sp_nosoil_nresp_group_policy_20260802.csv")
    budgets = dict(zip(budget_rows["group"].str.upper(), budget_rows["phi_budget"].astype(float)))
    fairness = active.groupby(["season_id", "_family"], as_index=False)["weighted_variance"].sum()
    fairness["declared_budget"] = fairness.apply(lambda r: budgets.get(str(r["_family"]).upper(), float("nan")), axis=1)
    fairness["abs_error"] = (fairness["weighted_variance"] - fairness["declared_budget"]).abs()
    if (fairness["abs_error"] > 1e-6).any():
        raise RuntimeError("T8 group budget mismatch: " + fairness.to_json(orient="records"))
    return {
        "n_registry_rows": int(len(registry)),
        "n_active_observations": int(len(active)),
        "n_adjustable_parameters": int(pyemu.Pst(str(out / f"{case}.pst")).npar_adj),
        "active_seasons": sorted(seasons),
        "soil_water_active": soil_active,
        "nresp_active": nresp_active,
        "duplicate_observation_names": int(registry["obsnme"].duplicated().sum()),
        "run_mapping_rows": int(len(mapping)),
        "instruction_tokens": int(len(ins_names)),
        "instruction_registry_missing": int(len(missing_ins)),
        "instruction_registry_extra": int(len(extra_ins)),
        "fairness_buckets": int(len(fairness)),
        "fairness_max_abs_error": float(fairness["abs_error"].max()) if len(fairness) else 0.0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id")
    ap.add_argument("--n-reals", type=int, default=200)
    ap.add_argument("--noptmax", type=int, default=4)
    ap.add_argument("--n-agents", type=int, default=6)
    ap.add_argument("--host", default="127.0.0.1", help="PEST++ manager host")
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    case = args.run_id or f"e02_v2_joint25sp26sp_nosoil_nresp_{args.n_reals}x{args.noptmax}_{datetime.now():%Y%m%d_%H%M%S}"
    out = ROOT / "workspace/runs" / case
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)
    run([
        sys.executable, str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2", "--multiseason-design", str(SOURCE_DESIGN),
        "--input-dir", str(ROOT / "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801"),
        "--bounds-id", BOUNDS_ID, "--bounds-crop", "eggplant", "--prefix", case,
        "--noptmax", str(args.noptmax), "--ies-num-reals", str(args.n_reals),
        "--random-seed", "20260802", "--bad-phi-sigma", "1e300",
        "--batch", str(ROOT / "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801/DSSBatch.v48"),
        "--harvest-var", "CHPDT", "--include-n-uptake", "--include-soil",
        "--out-dir", str(out), "--param-review-mode", "off",
        "--observation-policy-csv", str(POLICY), "--initial-ensemble-method", "sobol",
    ])
    preflight = audit_observation_contract(out, case, expected_params=99)
    receipt = {
        "run_id": case,
        "source_bounds": BOUNDS_ID,
        "design": str(SOURCE_DESIGN),
        "observation_policy": str(POLICY),
        "seasons": ["25SP", "26SP"],
        "n_reals": args.n_reals,
        "noptmax": args.noptmax,
        "initial_ensemble_method": "sobol",
        "status": "built",
        "preflight": preflight,
    }
    (out / "formal_launch_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Preflight passed:", json.dumps(receipt, ensure_ascii=False))
    if not args.execute:
        return 0
    run([
        sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(out), "--case", case, "--mode", "ies",
        "--n-agents", str(args.n_agents), "--host", args.host, "--wait",
    ])
    status = json.loads((out / "run_status.json").read_text(encoding="utf-8"))
    receipt["status"] = status.get("engineering_status", status.get("status"))
    receipt["run_status"] = status
    (out / "formal_launch_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if receipt["status"] != "engineering_validated":
        raise RuntimeError(receipt["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
