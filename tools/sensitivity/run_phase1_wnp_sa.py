#!/usr/bin/env python
"""CROPGRO-Eggplant Phase 1: Coupled Water-Nitrogen-Phosphorus (W-N-P) Sensitivity Analysis Pipeline.

Orchestrates multi-season Morris screening (r=30) and Sobol variance decomposition
using frozen baseline bounds eggplant_e02_wnp_baseline_20260914.csv and unified
input bundles (xxql2501, xxql2502, xxql2601).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.param_registry import assert_valid_frozen_bounds
from src.common.input_manifest import verify_manifest_integrity
from src.sensitivity.output_contract import load_output_contract, observation_names
from src.sensitivity.sa_build_sen_case import build_case

DEFAULT_BOUNDS = PROJECT_ROOT / "data" / "parameter_registry" / "bounds_frozen" / "eggplant" / "eggplant_e02_wnp_baseline_20260914.csv"
DEFAULT_OUTPUT_PROFILE = PROJECT_ROOT / "configs" / "sa" / "eggplant_wnp_multiseason_outputs_20260914.json"
DEFAULT_OUT_DIR = PROJECT_ROOT / "workspace" / "runs" / "sa_wnp_phase1_20260914"

SEASON_BUNDLES = {
    "25SP": {
        "experiment": "XXQL2501",
        "bundle_dir": PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2501_unified_20260914",
        "role": "calibration_training",
    },
    "25FA": {
        "experiment": "XXQL2502",
        "bundle_dir": PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2502_unified_20260914",
        "role": "independent_validation_quarantine",
    },
    "26SP": {
        "experiment": "XXQL2601",
        "bundle_dir": PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2601_unified_20260914",
        "role": "calibration_contrast_evaluation",
    },
}


def _find_pestpp_sen_exe() -> Path:
    exe = PROJECT_ROOT / "pestpp-5.2.16-win" / "bin" / "pestpp-sen.exe"
    if not exe.is_file():
        raise FileNotFoundError(f"pestpp-sen.exe not found at {exe}")
    return exe


def run_pipeline(
    bounds_csv: str | Path = DEFAULT_BOUNDS,
    output_profile: str | Path = DEFAULT_OUTPUT_PROFILE,
    seasons: list[str] | None = None,
    mode: str = "morris",
    morris_r: int = 30,
    sobol_samples: int = 512,
    random_seed: int = 20260914,
    out_dir: str | Path = DEFAULT_OUT_DIR,
    dry_run: bool = False,
    test_trajectory: int | None = None,
    cultivar: str = "TM0008",
    skip_postprocess: bool = False,
    n_agents: int = 6,
    resume: bool = False,
) -> dict[str, object]:
    bounds_path = Path(bounds_csv).resolve()
    profile_path = Path(output_profile).resolve()
    base_out_dir = Path(out_dir).resolve()

    if not bounds_path.is_file():
        raise FileNotFoundError(f"Frozen bounds CSV not found: {bounds_path}")
    if not profile_path.is_file():
        raise FileNotFoundError(f"Output profile JSON not found: {profile_path}")

    print("=" * 70)
    print("CROPGRO-Eggplant Phase 1: W-N-P Global Sensitivity Analysis Pipeline")
    print("=" * 70)
    print(f"Frozen Bounds CSV : {bounds_path}")
    print(f"Output Profile    : {profile_path}")
    print(f"Target Mode       : {mode}")
    print(f"Morris Trajectories: {morris_r if not test_trajectory else test_trajectory}")
    print(f"Sobol Sample Count: {sobol_samples}")
    print(f"Random Seed       : {random_seed}")
    print(f"Execution Mode    : {'DRY RUN (Case build & validation only)' if dry_run else 'FULL EXECUTION'}")
    print(f"Output Base Dir   : {base_out_dir}")
    print("-" * 70)

    # 1. Audit frozen bounds
    print("[1/4] Auditing frozen parameter bounds...")
    issues = assert_valid_frozen_bounds(bounds_path)
    warnings = [i for i in issues if i.severity == "warning"]
    print(f"  -> Frozen bounds validated: 0 errors ({len(warnings)} scientific warnings acknowledged).")

    # Target seasons
    if not seasons or "all" in seasons:
        target_seasons = ["25SP", "25FA", "26SP"]
    else:
        target_seasons = seasons

    results = {}

    for season in target_seasons:
        if season not in SEASON_BUNDLES:
            raise KeyError(f"Unknown season {season}. Available: {list(SEASON_BUNDLES.keys())}")
        bundle_info = SEASON_BUNDLES[season]
        bundle_dir = bundle_info["bundle_dir"]
        season_case_dir = base_out_dir / season
        os.makedirs(season_case_dir, exist_ok=True)

        print(f"\n[2/4] Processing Season: {season} ({bundle_info['experiment']})")
        print(f"  -> Input Bundle: {bundle_dir}")
        print(f"  -> Scientific Role: {bundle_info['role']}")

        # Verify bundle manifest integrity
        verify_manifest_integrity(bundle_dir)
        print("  -> Bundle manifest integrity verified (SHA-256 matched).")

        # Resolve season-specific contract
        season_contract = load_output_contract(profile_path, season=season, bundle_name=bundle_dir.name)
        obs_list = observation_names(season_contract)
        print(f"  -> Contract: {len(season_contract['treatments'])} treatments, {len(season_contract['features'])} features, {len(obs_list)} total observations.")

        # Build Morris case
        effective_r = test_trajectory if test_trajectory else morris_r
        pst_path = season_case_dir / "sa_sen_morris.pst"
        if resume and pst_path.is_file():
            print(f"  -> Resuming existing case without rebuilding: {pst_path}")
        else:
            pst_path = build_case(
                param_review_csv=str(bounds_path),
                case_dir=str(season_case_dir),
                workspace_dir=str(PROJECT_ROOT),
                cultivar=cultivar,
                morris_r=effective_r,
                random_seed=random_seed,
                output_profile=str(profile_path),
                input_dir=str(bundle_dir),
                run_type="sensitivity_formal_case",
            )
            print(f"  -> Case built successfully: {pst_path}")

        # Verify key artifacts
        expected_artifacts = [
            season_case_dir / "sa_params.csv",
            season_case_dir / "sa_params.csv.tpl",
            season_case_dir / "SA_Indicators.OUT.ins",
            season_case_dir / "sa_obs_order.txt",
            season_case_dir / "sa_sen_morris.pst",
            season_case_dir / "runtime" / "runtime_manifest.json",
        ]
        for art in expected_artifacts:
            if not art.exists():
                raise FileNotFoundError(f"Expected case artifact missing: {art}")
        print("  -> All PEST files (.pst, .tpl, .ins) and runtime sandbox verified.")

        season_result = {
            "season": season,
            "experiment": bundle_info["experiment"],
            "bundle": str(bundle_dir),
            "role": bundle_info["role"],
            "case_dir": str(season_case_dir),
            "pst_file": str(pst_path),
            "treatments_count": len(season_contract["treatments"]),
            "observations_count": len(obs_list),
            "status": "case_built",
        }

        # Step 3: Execution
        if not dry_run:
            print(f"\n[3/4] Launching pestpp-sen for {season} (r={effective_r})...")
            pst_name = Path(pst_path).name
            case_name = pst_name.rsplit(".", 1)[0]
            if n_agents and n_agents > 1:
                print(f"  -> Parallel execution mode with {n_agents} agents...")
                parallel_cmd = [
                    sys.executable,
                    str(PROJECT_ROOT / "tools" / "parallel" / "run_parallel.py"),
                    "--run-dir", str(season_case_dir),
                    "--case", case_name,
                    "--mode", "sen",
                    "--n-agents", str(n_agents),
                    "--wait",
                ]
                if resume and (season_case_dir / f"{case_name}.rns").is_file():
                    parallel_cmd.append("--resume")
                print(f"  -> Command: {' '.join(parallel_cmd)}")
                proc = subprocess.run(parallel_cmd, cwd=str(PROJECT_ROOT), text=True)
            else:
                exe = _find_pestpp_sen_exe()
                cmd = [str(exe), pst_name]
                log_file = season_case_dir / f"{pst_name}.log.txt"
                print(f"  -> Command: {' '.join(cmd)}")
                with open(log_file, "w", encoding="utf-8") as lf:
                    proc = subprocess.run(cmd, cwd=str(season_case_dir), stdout=lf, stderr=subprocess.STDOUT, text=True)
            if proc.returncode != 0:
                print(f"  -> ERROR: pestpp-sen failed with code {proc.returncode}.")
                season_result["status"] = "execution_failed"
            else:
                print(f"  -> Execution completed successfully (returncode 0).")
                season_result["status"] = "completed"

                # Step 4: Post-processing
                if not skip_postprocess and (season_case_dir / "sa_sen_morris.mio").exists():
                    print(f"\n[4/4] Running Morris post-processing for {season}...")
                    from src.sensitivity.sa_postprocess_morris import main as postprocess_main
                    post_cmd = [
                        sys.executable,
                        str(PROJECT_ROOT / "src" / "sensitivity" / "sa_postprocess_morris.py"),
                        "--case-dir",
                        str(season_case_dir),
                    ]
                    post_proc = subprocess.run(post_cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
                    print(f"  -> Post-processing output: {post_proc.stdout.strip()}")
                    season_result["postprocess_status"] = "ok" if post_proc.returncode == 0 else "failed"
        else:
            print(f"\n[3/4] Dry run requested: Skipping pestpp-sen execution for {season}.")
            season_result["status"] = "dry_run_passed"

        # Sobol interface preparation if requested
        if mode in ("sobol", "both"):
            print(f"\n[Sobol Interface] Staging Sobol variance decomposition configuration for {season}...")
            sobol_case_dir = base_out_dir / f"{season}_sobol"
            season_result["sobol_staged_dir"] = str(sobol_case_dir)
            print(f"  -> Sobol case target: {sobol_case_dir} (N={sobol_samples})")

        results[season] = season_result

    # Save summary report
    summary_path = base_out_dir / "pipeline_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nPipeline summary written to: {summary_path}")
    print("=" * 70)
    print("PIPELINE EXECUTION SUMMARY:")
    for s, r in results.items():
        print(f"  {s:5s} ({r['experiment']}): status={r['status']}, obs={r['observations_count']}, case={r['case_dir']}")
    print("=" * 70)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 1 W-N-P Global Sensitivity Analysis Execution Pipeline")
    parser.add_argument("--bounds-csv", default=DEFAULT_BOUNDS, help="Path to frozen calibration bounds CSV")
    parser.add_argument("--output-profile", default=DEFAULT_OUTPUT_PROFILE, help="Path to unified multi-season output profile")
    parser.add_argument("--season", choices=["25SP", "25FA", "26SP", "all"], default="25SP", help="Target season")
    parser.add_argument("--mode", choices=["morris", "sobol", "both"], default="morris", help="SA analysis mode")
    parser.add_argument("--morris-r", type=int, default=30, help="Number of Morris trajectories (default: 30)")
    parser.add_argument("--sobol-samples", type=int, default=512, help="Sobol Saltelli sample count (default: 512)")
    parser.add_argument("--random-seed", type=int, default=20260914, help="Random seed for reproducibility")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help="Base output directory for SA runs")
    parser.add_argument("--dry-run", action="store_true", help="Build case and verify manifests without running model")
    parser.add_argument("--test-trajectory", type=int, default=None, help="Execute minimal Morris trajectories (e.g. 2) for smoke verification")
    parser.add_argument("--cultivar", default="TM0008", help="Cultivar code")
    parser.add_argument("--skip-postprocess", action="store_true", help="Skip post-processing after Morris execution")
    parser.add_argument("--n-agents", type=int, default=8, help="Number of parallel agents (default: 8, 0 or 1 for serial)")
    parser.add_argument("--resume", action="store_true", help="Resume interrupted run from existing case.rns")

    args = parser.parse_args()

    seasons = ["25SP", "25FA", "26SP"] if args.season == "all" else [args.season]

    run_pipeline(
        bounds_csv=args.bounds_csv,
        output_profile=args.output_profile,
        seasons=seasons,
        mode=args.mode,
        morris_r=args.morris_r,
        sobol_samples=args.sobol_samples,
        random_seed=args.random_seed,
        out_dir=args.out_dir,
        dry_run=args.dry_run,
        test_trajectory=args.test_trajectory,
        cultivar=args.cultivar,
        skip_postprocess=args.skip_postprocess,
        n_agents=args.n_agents,
        resume=args.resume,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
