"""Run the three-season actual-N E02 calibration with LHS and reinflation."""

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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.calibration.initial_ensemble import generate_lhs_ensemble, write_ensemble_csv

DESIGN = (
    ROOT
    / "configs/runs"
    / "eggplant_e02_joint62_three_season_actualn_nochtd_lhs_v1_20260731.json"
)
POLICY = ROOT / "configs/runs/e02_n_response_snam_lnam_chpdtlog_noadap_nochtd_v1.csv"
GROUP_POLICY = ROOT / "configs/runs/t10_n_response_group_policy_harvestdry250_v2.csv"
BOUNDS_ID_DEFAULT = "eggplant_e02_joint62_v7_nstfac050_rhght035_posterior15_offset0_phys_20260731"
INPUT_DIR = (
    ROOT
    / "data/user/experiments"
    / "xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729"
)
EXPECTED_SEASONS = {"25SP", "25FA", "26SP"}


def run(command: list[str]) -> None:
    print("+ " + subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def apply_ies_profile(
    run_dir: Path,
    case: str,
    *,
    n_reals: int,
    seed: int,
    initial_ensemble_method: str,
    reinflate_iterations: int,
    reinflate_factor: float | None,
) -> None:
    path = run_dir / f"{case}.pst"
    pst = pyemu.Pst(str(path))

    if initial_ensemble_method in {"lhs", "sobol"}:
        par_df = pst.parameter_data.copy()
        bounds_df = pd.DataFrame(
            {
                "name": par_df["parnme"],
                "init": pd.to_numeric(par_df["parval1"], errors="coerce"),
                "lower": pd.to_numeric(par_df["parlbnd"], errors="coerce"),
                "upper": pd.to_numeric(par_df["parubnd"], errors="coerce"),
                "status": [
                    "fixed" if str(v).strip().lower() == "fixed" else "active"
                    for v in par_df["partrans"]
                ],
            }
        )
        active_df = generate_lhs_ensemble(
            n_reals=n_reals,
            bounds_df=bounds_df,
            seed=seed,
            method=initial_ensemble_method,
            include_base=False,
        )
        ensemble_df = pd.DataFrame({"real_name": active_df["real_name"]})
        active_cols = set(active_df.columns) - {"real_name"}
        for row in bounds_df.itertuples(index=False):
            name = str(row.name)
            if name in active_cols:
                ensemble_df[name] = active_df[name]
            else:
                ensemble_df[name] = float(row.init)
        ensemble_path = run_dir / f"{case}.0.par.csv"
        write_ensemble_csv(ensemble_df, ensemble_path)
        pst.pestpp_options["ies_parameter_ensemble"] = ensemble_path.name

    if reinflate_iterations > 0:
        pst.pestpp_options["ies_n_iter_reinflate"] = reinflate_iterations

    pst.write(str(path))


def verify(
    run_dir: Path,
    case: str,
    n_reals: int,
    noptmax: int,
    bounds_id: str,
    observation_policy_path: Path,
    initial_ensemble_method: str,
    reinflate_iterations: int,
    reinflate_factor: float | None,
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

    active_bounds = bounds.loc[bounds["status"].astype(str).str.lower().eq("active")].copy()
    expected_active = int(len(active_bounds))
    if pst.npar_adj != expected_active:
        problems.append(f"expected {expected_active} adjustable terms; PST={pst.npar_adj}")
    if int(pst.control_data.noptmax) != noptmax:
        problems.append(f"expected noptmax={noptmax}")
    if int(pst.pestpp_options.get("ies_num_reals", -1)) != n_reals:
        problems.append(f"expected ies_num_reals={n_reals}")

    method_in_pst = str(pst.pestpp_options.get("ies_parameter_ensemble", "")).strip()
    if initial_ensemble_method == "random":
        if method_in_pst:
            problems.append("random initial ensemble requested but ies_parameter_ensemble is set")
    else:
        if not method_in_pst.endswith(".0.par.csv"):
            problems.append(
                f"expected ies_parameter_ensemble CSV for {initial_ensemble_method}, got {method_in_pst or 'missing'}"
            )
        csv_path = run_dir / method_in_pst
        if not csv_path.is_file():
            problems.append(f"initial ensemble file missing: {csv_path}")

    reinflate_value = int(float(pst.pestpp_options.get("ies_n_iter_reinflate", 0) or 0))
    if reinflate_value != reinflate_iterations:
        problems.append(
            f"expected ies_n_iter_reinflate={reinflate_iterations}, found {reinflate_value}"
        )
    if reinflate_factor is not None:
        actual_factor = float(pst.pestpp_options.get("ies_reinflate_factor", -1))
        if abs(actual_factor - reinflate_factor) > 1e-9:
            problems.append(
                f"expected ies_reinflate_factor={reinflate_factor}, found {actual_factor}"
            )

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

    if problems:
        raise RuntimeError("LHS/reinflation three-season preflight failed: " + "; ".join(problems))

    return {
        "run_id": case,
        "run_dir": str(run_dir),
        "design": str(DESIGN),
        "bounds_id": bounds_id,
        "n_parameters_adjustable": int(pst.npar_adj),
        "n_parameters_active_in_bounds": expected_active,
        "n_observations_active": int(pst.nnz_obs),
        "active_seasons": sorted(season_ids),
        "n_reals": n_reals,
        "noptmax": noptmax,
        "initial_ensemble_method": initial_ensemble_method,
        "ies_parameter_ensemble": method_in_pst,
        "ies_reinflate": reinflate_value,
        "ies_reinflate_factor": reinflate_factor,
        "adap_role": "diagnostic_only",
        "chtd_role": "diagnostic_only",
        "harvest_dry_budget": 2.5,
        "filex_initial_mineral_n": "actual FileX values",
        "status": "built",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id")
    parser.add_argument("--n-reals", type=int, default=250)
    parser.add_argument("--noptmax", type=int, default=5)
    parser.add_argument("--n-agents", type=int, default=6)
    parser.add_argument("--random-seed", type=int, default=20260731)
    parser.add_argument("--bounds-id", default=BOUNDS_ID_DEFAULT)
    parser.add_argument("--observation-policy", default=str(POLICY))
    parser.add_argument(
        "--initial-ensemble-method",
        choices=["random", "lhs", "sobol"],
        default="lhs",
    )
    parser.add_argument("--reinflate-iterations", type=int, default=1)
    parser.add_argument("--reinflate-factor", type=float, default=None)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    observation_policy = Path(args.observation_policy)

    run_id = args.run_id or (
        f"e02_joint62_three_season_lhs_reinflation_"
        f"{args.n_reals}x{args.noptmax}_{datetime.now():%Y%m%d_%H%M%S}"
    )
    run_dir = ROOT / "workspace/runs" / run_id
    if run_dir.exists():
        raise FileExistsError(run_dir)

    build_cmd = [
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
        "--initial-ensemble-method",
        args.initial_ensemble_method,
        "--reinflate-iterations",
        str(args.reinflate_iterations),
    ]
    if args.reinflate_factor is not None:
        build_cmd.extend(["--reinflate-factor", str(args.reinflate_factor)])
    run(build_cmd)
    apply_ies_profile(
        run_dir,
        run_id,
        n_reals=args.n_reals,
        seed=args.random_seed,
        initial_ensemble_method=args.initial_ensemble_method,
        reinflate_iterations=args.reinflate_iterations,
        reinflate_factor=args.reinflate_factor,
    )

    receipt = verify(
        run_dir,
        run_id,
        args.n_reals,
        args.noptmax,
        args.bounds_id,
        observation_policy,
        args.initial_ensemble_method,
        args.reinflate_iterations,
        args.reinflate_factor,
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
    print(f"Engineering validation passed: {receipt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
