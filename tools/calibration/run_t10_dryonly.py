"""T10 dry-only calibration: CHFPW (fresh) dropped from Phi, CHPDT (dry) only.

This is a configuration-only variant of the approved T10 contract.  It reuses
the existing ``build_pest.py`` / ``build_pest_multiseason.py`` machinery
unchanged; the only differences from the reference T10 run are:

* the observation policy CSV sets ``CHFPWM`` to ``diagnostic_only`` (zero weight)
  and tightens ``CHPDTM`` sigma 250 -> 200 (dry magnitude ~3000-3500 vs fresh
  ~67000), so CHPDT is the sole active harvest family;
* the group-policy CSV removes the now-unused ``HARVEST_FRESH`` family and keeps
  ``HARVEST_DRY`` at 1.25 (no reallocation);
* the preflight asserts CHFPW has NO active weight and CHPDT is active.

Two scopes are supported, matching the two reference T10 runners:
  * ``single`` -- the matched 25SP/25FA single-season diagnostics
    (cf. ``run_t10_single_season_diagnostic.py``);
  * ``joint``  -- the two-season joint calibration (cf.
    ``run_t10_formal_multiseason.py``).

Smoke = 20 realizations / 1 update; formal = 200 realizations / 4 updates.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyemu


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "configs" / "runs" / "assumption_based_sigma_v5_dryonly.csv"
BOUNDS_ID = "eggplant_t10_m0_v1_20260722"

SINGLE_DESIGNS = {
    "25SP": ROOT / "configs" / "runs" / "eggplant_t10_dryonly_diagnostic_25sp_v1.json",
    "25FA": ROOT / "configs" / "runs" / "eggplant_t10_dryonly_diagnostic_25fa_v1.json",
}
SINGLE_BATCH_PARENT = {
    "25SP": ROOT / "data" / "user" / "experiments" / "xxql2501_20260716",
    "25FA": ROOT / "data" / "user" / "experiments" / "xxql2502_actual_trial_calibration_v1_20260721",
}
JOINT_DESIGN = ROOT / "configs" / "runs" / "eggplant_t10_dryonly_joint_25sp_25fa_v1.json"
JOINT_BATCH_PARENT = ROOT / "data" / "user" / "experiments" / "xxql2501_20260716"

# Shared numerical profile (identical to the reference T10 runners) so the
# aggressive default trial updates cannot become the sole reason one scope or
# season loses more realizations than another.
IES_STABILITY_PROFILE = {
    "ies_use_approx": False,
    "ies_lambda_mults": "0.5,1.0,10.0",
    "lambda_scale_fac": "0.9,1.0",
    "ies_enforce_bounds": True,
}

EXPECTED_ACTIVE_PARAMS = 41
# CHPDT sigma tightening (v5 dry-only policy): the policy CSV column values are
# sigma=200, model_sigma=25, sigma_floor=15.  apply_observation_policy combines
# them as raw_sigma = sqrt(sigma**2 + model**2 + floor**2); the audit CSV stores
# that combined raw_sigma, so the preflight must check the combined value, not
# the bare column value.
CHPDT_SIGMA_COLUMN = 200.0
CHPDT_MODEL_SIGMA = 25.0
CHPDT_SIGMA_FLOOR = 15.0
CHPDT_EXPECTED_RAW_SIGMA = math.sqrt(
    CHPDT_SIGMA_COLUMN**2 + CHPDT_MODEL_SIGMA**2 + CHPDT_SIGMA_FLOOR**2
)
# The original (v4) combined raw_sigma for CHFPW/CHPDT was sqrt(250**2+30**2+20**2).
V4_RAW_SIGMA = math.sqrt(250.0**2 + 30.0**2 + 20.0**2)


def _run(command: list[str]) -> None:
    print("+ " + subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def _apply_stability_profile(run_dir: Path, case: str) -> None:
    path = run_dir / f"{case}.pst"
    pst = pyemu.Pst(str(path))
    pst.pestpp_options.update(IES_STABILITY_PROFILE)
    pst.write(str(path))


def _bounds_frame() -> pd.DataFrame:
    return pd.read_csv(
        ROOT / "data" / "parameter_registry" / "bounds_frozen" / "eggplant" / f"{BOUNDS_ID}.csv",
        encoding="utf-8-sig",
    )


def _verify_dryonly(
    run_dir: Path, case: str, n_reals: int, noptmax: int, *, joint: bool
) -> dict[str, object]:
    """Reject a build that is not the dry-only T10 scientific contract."""
    pst = pyemu.Pst(str(run_dir / f"{case}.pst"))
    obs = pst.observation_data.copy()
    names = obs["obsnme"].astype(str).str.upper()
    active = obs.loc[pd.to_numeric(obs["weight"], errors="coerce") > 0].copy()
    active_names = active["obsnme"].astype(str).str.upper()
    bounds = _bounds_frame()
    transform_path = run_dir / f"{case}.observation_transforms.json"
    registry_path = run_dir / f"{case}_observation_registry.csv"
    registry = (
        pd.read_csv(registry_path, encoding="utf-8-sig") if registry_path.is_file() else pd.DataFrame()
    )
    problems: list[str] = []

    # --- core IES / culling / count guards (identical to reference T10) ---
    if int(pst.control_data.noptmax) != noptmax:
        problems.append(f"NOPTMAX must be {noptmax}")
    if int(pst.pestpp_options.get("ies_num_reals", -1)) != n_reals:
        problems.append("IES realization count does not match launch request")
    if float(pst.pestpp_options.get("ies_bad_phi_sigma", 0.0)) < 1e299:
        problems.append("automatic relative-Phi culling must be disabled")
    expected_active = int(bounds["status"].astype(str).str.lower().eq("active").sum())
    if pst.npar_adj != expected_active:
        problems.append(f"expected {expected_active} adjustable parameters, got {pst.npar_adj}")
    if any(str(name).upper().endswith("_AUT") for name in pst.parameter_data.index):
        problems.append("this T10-M0 variant must not contain autumn offset parameters")

    # --- legacy / forbidden harvest guards (identical) ---
    if names.str.contains("PWAD|PWAI|HWAM").any():
        problems.append("legacy PWAD/PWAI/HWAM must not enter the objective")
    if names.str.contains("LAIX").any() and active_names.str.contains("LAIX").any():
        problems.append("LAIX must remain diagnostic-only")

    # --- DRY-ONLY harvest contract (the defining difference) ---
    # CHFPW must have NO active weight; CHPDT must be active.
    if active_names.str.contains("CHFPW").any():
        problems.append("CHFPW (fresh) must be diagnostic-only with zero weight in the dry-only variant")
    if not active_names.str.contains("CHPDT").any():
        problems.append("CHPDT (dry) has no active direct-harvest observations")

    # --- CHPDT sigma tightening audit ---
    # raw_sigma in the audit is the combined sqrt(sigma**2 + model**2 + floor**2).
    weights_audit_path = run_dir / f"{case}.weights.audit.csv"
    if weights_audit_path.is_file():
        audit = pd.read_csv(weights_audit_path, encoding="utf-8-sig")
        chpdt_rows = audit[
            audit["obgnme"].astype(str).str.upper().str.contains("CHPDTM")
        ]
        if not chpdt_rows.empty:
            raw_sigma = pd.to_numeric(chpdt_rows.get("raw_sigma"), errors="coerce").dropna().unique()
            if len(raw_sigma) and not pd.Series(raw_sigma).apply(
                lambda v: abs(float(v) - CHPDT_EXPECTED_RAW_SIGMA) < 1e-6
            ).all():
                problems.append(
                    f"CHPDT raw_sigma must equal the tightened combined value "
                    f"{CHPDT_EXPECTED_RAW_SIGMA:.4f} (sigma={CHPDT_SIGMA_COLUMN}, "
                    f"model={CHPDT_MODEL_SIGMA}, floor={CHPDT_SIGMA_FLOOR}), "
                    f"got {sorted(raw_sigma.tolist())}"
                )

    # --- joint-specific guards (mirror run_t10_formal_multiseason preflight) ---
    if joint:
        if len(registry) != len(obs) or set(registry["season_id"].astype(str)) != {"25SP", "25FA"}:
            problems.append("observation registry must contain both calibration seasons only")
        groups_path = run_dir / f"{case}_group_weight_audit.csv"
        if not groups_path.is_file():
            problems.append("group-weight audit is missing")
        else:
            groups = pd.read_csv(groups_path, encoding="utf-8-sig")
            if set(groups["season_id"].astype(str)) != {"25SP", "25FA"}:
                problems.append("group-weight audit lacks a family-season allocation for a calibration season")
            if groups.duplicated(["season_id", "variable_family"]).any():
                problems.append("family-season budget was allocated more than once")
        xfpht = bounds.loc[bounds["name"].astype(str).str.upper().eq("XFPHT")]
        if len(xfpht) != 1 or float(xfpht.iloc[0]["lower"]) != 31.0 or float(xfpht.iloc[0]["upper"]) != 70.0:
            problems.append("XFPHT frozen bounds must be 31-70")
        xfint = bounds.loc[bounds["name"].astype(str).str.upper().eq("XFINT")]
        if len(xfint) != 1 or float(xfint.iloc[0]["lower"]) != 0.08 or float(xfint.iloc[0]["upper"]) != 0.50:
            problems.append("XFINT frozen bounds must be 0.08-0.50")
        command = " ".join(pst.model_command)
        if "--observation-transform-config" not in command:
            problems.append("multi-season model command dropped the transform configuration")
    else:
        # single-season: registry must contain only this season.
        if not registry.empty and set(registry["season_id"].astype(str)) != {
            _season_from_case(case)
        }:
            problems.append(f"observation registry must contain only {_season_from_case(case)}")

    # --- transform contract: CHPDTS must be ln(y+1).  CHFPWS keeps the same
    # transform (apply_observation_policy still emits it for diagnostic log
    # groups); assert CHPDTS explicitly, leave CHFPWS optional. ---
    if not transform_path.is_file():
        problems.append("audited observation transform configuration is missing")
    else:
        transform = json.loads(transform_path.read_text(encoding="utf-8"))
        harvest_tokens = transform.get("files", {}).get("PestHarvest.OUT", {})
        chpdts_spec = harvest_tokens.get("CHPDTS")
        if chpdts_spec != {"transform": "log", "offset": 1.0, "reference": 1.0}:
            problems.append("CHPDTS must use exactly ln((y+1)/1)")

    # --- IES stability profile (identical) ---
    for key, value in IES_STABILITY_PROFILE.items():
        if str(pst.pestpp_options.get(key)).strip().lower() != str(value).strip().lower():
            problems.append(f"IES stability option {key} differs from comparator profile")

    if problems:
        raise RuntimeError("T10 dry-only preflight failed: " + "; ".join(problems))

    receipt = {
        "pst": str(run_dir / f"{case}.pst"),
        "status": "built",
        "diagnostic_only": not joint,
        "scope": "joint_multiseason" if joint else "single_season",
        "season": None if joint else _season_from_case(case),
        "calibration_seasons": ["25SP", "25FA"] if joint else [_season_from_case(case)],
        "n_parameters_adjustable": int(pst.npar_adj),
        "n_observations_total": int(len(obs)),
        "n_observations_active": int(pst.nnz_obs),
        "n_reals": int(n_reals),
        "noptmax": int(noptmax),
        "bounds_id": BOUNDS_ID,
        "harvest_contract": "dry_only_chpdt",
        "chfpw_status": "diagnostic_only_zero_weight",
        "chpdt_sigma": CHPDT_SIGMA_COLUMN,
        "chpdt_model_sigma": CHPDT_MODEL_SIGMA,
        "chpdt_sigma_floor": CHPDT_SIGMA_FLOOR,
        "chpdt_combined_raw_sigma": round(CHPDT_EXPECTED_RAW_SIGMA, 6),
        "chpdt_budget": 1.25,
        "chfpw_budget": "retained at 1.25 but inert (no active fresh observations)",
        "objective": "direct CHPDT only; ln(y+1); CHFPW diagnostic; no PWAD/PWAI/HWAM",
        "ies_profile": IES_STABILITY_PROFILE,
        "interpretation": (
            "compare single-season conditional posteriors; do not report either as a final "
            "cultivar parameter set"
            if not joint
            else "joint dry-only calibration; validation season 26SP remains sealed"
        ),
    }
    return receipt


def _season_from_case(case: str) -> str:
    # case ids are suffixed _25sp / _25fa
    tail = case.rsplit("_", 1)[-1].upper()
    return {"25SP": "25SP", "25FA": "25FA"}.get(tail, tail)


def _build(
    *, design: Path, batch_parent: Path, run_id: str, n_reals: int, noptmax: int, seed: int
) -> Path:
    run_dir = ROOT / "workspace" / "runs" / run_id
    if run_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing run directory: {run_dir}")
    batch = batch_parent / "DSSBatch.v48"
    _run([
        sys.executable, str(ROOT / "src" / "calibration" / "build_pest.py"),
        "--mode", "eggplant_stage2", "--multiseason-design", str(design),
        "--input-dir", str(batch_parent), "--bounds-id", BOUNDS_ID, "--bounds-crop", "eggplant",
        "--prefix", run_id, "--noptmax", str(noptmax), "--ies-num-reals", str(n_reals),
        "--random-seed", str(seed), "--bad-phi-sigma", "1e300",
        "--batch", str(batch), "--harvest-var", "CHPDT", "--include-n-uptake",
        "--out-dir", str(run_dir), "--param-review-mode", "off",
        "--observation-policy-csv", str(POLICY),
    ])
    _apply_stability_profile(run_dir, run_id)
    return run_dir


def _build_and_run(
    *, design: Path, batch_parent: Path, run_id: str, n_reals: int, noptmax: int,
    n_agents: int, seed: int, build_only: bool, joint: bool,
) -> dict[str, object]:
    run_dir = _build(
        design=design, batch_parent=batch_parent, run_id=run_id,
        n_reals=n_reals, noptmax=noptmax, seed=seed,
    )
    receipt = _verify_dryonly(run_dir, run_id, n_reals, noptmax, joint=joint)
    receipt.update({"run_id": run_id, "run_dir": str(run_dir), "design": str(design), "random_seed": seed})
    receipt_path = run_dir / "formal_launch_receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Preflight passed: {receipt_path}")
    if build_only:
        return receipt
    _run([
        sys.executable, str(ROOT / "tools" / "parallel" / "run_parallel.py"),
        "--run-dir", str(run_dir), "--case", run_id, "--mode", "ies",
        "--n-agents", str(n_agents), "--wait",
    ])
    status_path = run_dir / "run_status.json"
    status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.is_file() else {}
    eng = status.get("engineering_status")
    receipt["run_status"] = eng
    receipt["engineering_status_error"] = status.get("engineering_status_error")
    if eng != "engineering_validated":
        raise RuntimeError(
            f"{run_id} engineering gate did not pass: {eng} "
            + str(status.get("engineering_status_error") or eng)
        )
    receipt["status"] = "engineering_validated"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{run_id} calibration completed: {run_dir}")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="T10 dry-only calibration (CHFPW dropped, CHPDT only)."
    )
    parser.add_argument("--scope", choices=["single", "joint", "both"], default="both")
    parser.add_argument("--season", choices=["25SP", "25FA", "both"], default="both",
                        help="single-scope season selection (ignored for --scope joint)")
    parser.add_argument("--run-prefix", default=None)
    parser.add_argument("--n-agents", type=int, default=8)
    parser.add_argument("--n-reals", type=int, default=200)
    parser.add_argument("--noptmax", type=int, default=4, choices=[1, 4])
    parser.add_argument("--random-seed", type=int, default=20260723)
    parser.add_argument("--build-only", action="store_true",
                        help="build and preflight without launching PEST++")
    parser.add_argument("--smoke", action="store_true",
                        help="run a 20-member, one-update interface smoke; formal defaults remain 200/4")
    args = parser.parse_args(argv)
    if args.smoke:
        args.n_reals = 20
        args.noptmax = 1
    if args.n_agents < 1 or args.n_reals < 20:
        raise ValueError("require n_agents>=1 and n_reals>=20")
    if args.scope == "joint" and args.noptmax != 4 and not args.smoke:
        # mirror the reference formal wrapper's noptmax==4 expectation for the
        # joint formal run; smoke (noptmax 1) is permitted.
        parser.error("--scope joint formal run requires noptmax 4 (use --smoke for noptmax 1)")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = args.run_prefix or f"eggplant_t10_dryonly_{stamp}"
    do_single = args.scope in ("single", "both")
    do_joint = args.scope in ("joint", "both")

    if do_single:
        seasons = ["25SP", "25FA"] if args.season == "both" else [args.season]
        for season in seasons:
            # Deliberately sequential: two 8-agent managers would compete for the
            # same local DSSAT installation and make seasonal failure rates unequal.
            _build_and_run(
                design=SINGLE_DESIGNS[season],
                batch_parent=SINGLE_BATCH_PARENT[season],
                run_id=f"{prefix}_single_{season.lower()}",
                n_reals=args.n_reals, noptmax=args.noptmax,
                n_agents=args.n_agents, seed=args.random_seed,
                build_only=args.build_only, joint=False,
            )

    if do_joint:
        _build_and_run(
            design=JOINT_DESIGN,
            batch_parent=JOINT_BATCH_PARENT,
            run_id=f"{prefix}_joint",
            n_reals=args.n_reals, noptmax=args.noptmax,
            n_agents=args.n_agents, seed=args.random_seed,
            build_only=args.build_only, joint=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
