"""Run the 25SP-only E02 rerun with CHTD excluded from Phi and a lower RHGHT floor."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyemu


ROOT = Path(__file__).resolve().parents[2]
DESIGN = (
    ROOT
    / "configs/runs"
    / "eggplant_e02_single55_25sp_actualn_nochtd_rhghtrelax_v1_20260731.json"
)
POLICY = ROOT / "configs/runs/e02_n_response_snam_lnam_chpdtlog_noadap_nochtd_v1.csv"
GROUP_POLICY = ROOT / "configs/runs/t10_n_response_group_policy_harvestdry250_v2.csv"
BOUNDS_ID_DEFAULT = "eggplant_e02_single55_25sp_actualn_posterior15phys_rhght010_20260731"
INPUT_DIR = ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v2_20260726"
EXPECTED_SEASONS = {"25SP"}
IES_PROFILE = {
    "ies_use_approx": False,
    "ies_lambda_mults": "0.5,1.0,10.0",
    "lambda_scale_fac": "0.9,1.0",
    "ies_enforce_bounds": True,
}


def run(command: list[str]) -> None:
    print("+ " + subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def apply_ies_profile(run_dir: Path, case: str) -> None:
    path = run_dir / f"{case}.pst"
    pst = pyemu.Pst(str(path))
    pst.pestpp_options.update(IES_PROFILE)
    pst.write(str(path))


def verify(
    run_dir: Path,
    case: str,
    n_reals: int,
    noptmax: int,
    bounds_id: str,
    observation_policy_path: Path,
) -> dict:
    pst = pyemu.Pst(str(run_dir / f"{case}.pst"))
    registry = pd.read_csv(
        run_dir / f"{case}_observation_registry.csv", encoding="utf-8-sig"
    )
    policy = pd.read_csv(observation_policy_path, encoding="utf-8-sig")
    bounds = pd.read_csv(
        ROOT / f"data/parameter_registry/bounds_frozen/eggplant/{bounds_id}.csv",
        encoding="utf-8-sig",
    )
    groups = pd.read_csv(GROUP_POLICY, encoding="utf-8-sig")
    problems: list[str] = []

    active_bounds = bounds.loc[bounds["status"].astype(str).str.lower().eq("active")]
    if pst.npar_adj != 55:
        problems.append(f"expected 55 adjustable terms; PST={pst.npar_adj}")
    if len(active_bounds) != 55:
        problems.append(f"frozen bounds should expose 55 active terms; found {len(active_bounds)}")
    if int(pst.control_data.noptmax) != noptmax:
        problems.append(f"expected noptmax={noptmax}")
    if int(pst.pestpp_options.get("ies_num_reals", -1)) != n_reals:
        problems.append(f"expected ies_num_reals={n_reals}")
    if any(str(name).upper().endswith("_AUT") for name in pst.parameter_data.index):
        problems.append("single-season rerun must not contain seasonal offset parameters")

    active = registry.loc[pd.to_numeric(registry["weight"], errors="coerce") > 0]
    if len(active) != int(pst.nnz_obs):
        problems.append(
            f"registry/PST active observation mismatch: {len(active)} != {pst.nnz_obs}"
        )
    season_ids = set(active["season_id"].astype(str).unique())
    if season_ids != EXPECTED_SEASONS:
        problems.append(
            f"expected active seasons {sorted(EXPECTED_SEASONS)}, found {sorted(season_ids)}"
        )

    no_phi_groups = {
        str(row["group"]).strip().upper()
        for _, row in policy.iterrows()
        if str(row.get("phi_role", "")).strip().lower() == "diagnostic_only"
    }
    for token in sorted(no_phi_groups):
        masked = registry.loc[
            registry["obgnme"].astype(str).str.upper().str.contains(token, regex=False)
        ]
        if not masked.empty and (pd.to_numeric(masked["weight"], errors="coerce") > 0).any():
            problems.append(f"{token} entered Phi despite observation policy diagnostic_only")

    dry_budget = groups.loc[groups["group"].eq("HARVEST_DRY"), "phi_budget"]
    if len(dry_budget) != 1 or float(dry_budget.iloc[0]) != 2.5:
        problems.append("HARVEST_DRY budget must be 2.5")

    tracked_bounds = ("NSTFAC", "RHGHT", "SOIL_SLPF")
    observed_bounds: dict[str, list[float]] = {}
    for name in tracked_bounds:
        row = bounds.loc[bounds["name"].eq(name)]
        if len(row) != 1:
            problems.append(f"missing unique {name} bounds row")
            continue
        actual = (float(row.iloc[0]["lower"]), float(row.iloc[0]["upper"]))
        observed_bounds[name] = [actual[0], actual[1]]

    if problems:
        raise RuntimeError("E02 25SP preflight failed: " + "; ".join(problems))
    return {
        "run_id": case,
        "run_dir": str(run_dir),
        "design": str(DESIGN),
        "bounds_id": bounds_id,
        "n_parameters_adjustable": int(pst.npar_adj),
        "n_observations_active": int(pst.nnz_obs),
        "active_seasons": sorted(season_ids),
        "n_reals": n_reals,
        "noptmax": noptmax,
        "adap_role": "diagnostic_only",
        "chtd_role": "diagnostic_only",
        "harvest_dry_budget": 2.5,
        "targeted_bounds": observed_bounds,
        "filex_initial_mineral_n": "25SP actual FileX values",
        "status": "built",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id")
    parser.add_argument("--n-reals", type=int, default=200)
    parser.add_argument("--noptmax", type=int, default=6)
    parser.add_argument("--n-agents", type=int, default=6)
    parser.add_argument("--random-seed", type=int, default=20260730)
    parser.add_argument("--bounds-id", default=BOUNDS_ID_DEFAULT)
    parser.add_argument("--observation-policy", default=str(POLICY))
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    observation_policy = Path(args.observation_policy)

    run_id = args.run_id or f"e02_25sp_actualn_nochtd_rhghtrelax_{args.n_reals}x{args.noptmax}_{datetime.now():%Y%m%d_%H%M%S}"
    run_dir = ROOT / "workspace/runs" / run_id
    if run_dir.exists():
        raise FileExistsError(run_dir)

    run(
        [
            sys.executable,
            str(ROOT / "src/calibration/build_pest.py"),
            "--mode",
            "eggplant_stage2",
            "--multiseason-design",
            str(DESIGN),
            "--input-dir",
            str(INPUT_DIR),
            "--bounds-id",
            args.bounds_id,
            "--bounds-crop",
            "eggplant",
            "--prefix",
            run_id,
            "--noptmax",
            str(args.noptmax),
            "--ies-num-reals",
            str(args.n_reals),
            "--random-seed",
            str(args.random_seed),
            "--bad-phi-sigma",
            "1e300",
            "--batch",
            str(INPUT_DIR / "DSSBatch.v48"),
            "--harvest-var",
            "CHPDT",
            "--include-n-uptake",
            "--out-dir",
            str(run_dir),
            "--param-review-mode",
            "off",
            "--observation-policy-csv",
            str(observation_policy),
        ]
    )
    apply_ies_profile(run_dir, run_id)
    receipt = verify(
        run_dir,
        run_id,
        args.n_reals,
        args.noptmax,
        args.bounds_id,
        observation_policy,
    )
    receipt["observation_policy"] = str(observation_policy)
    receipt_path = run_dir / "formal_launch_receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Preflight passed: {receipt_path}")
    if not args.execute:
        return 0

    run(
        [
            sys.executable,
            str(ROOT / "tools/parallel/run_parallel.py"),
            "--run-dir",
            str(run_dir),
            "--case",
            run_id,
            "--mode",
            "ies",
            "--n-agents",
            str(args.n_agents),
            "--wait",
        ]
    )
    status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    if status.get("engineering_status") != "engineering_validated":
        raise RuntimeError(
            status.get("engineering_status_error") or status.get("engineering_status")
        )
    receipt["status"] = "engineering_validated"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
