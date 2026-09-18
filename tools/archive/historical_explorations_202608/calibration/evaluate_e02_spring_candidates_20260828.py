"""Deterministically evaluate E02 candidates with held-out spring treatments first.

The four calibration treatments per spring season remain labelled calibration;
all other treatments with audited observations are labelled validation.  25FA
is intentionally absent and stays locked until the final candidate rule is
frozen.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools" / "analysis") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools" / "analysis"))

from render_arm_d_best17_diagnostics_20260820 import (  # noqa: E402
    build_season_harvest_compare,
    build_season_process_compare,
    compute_metrics,
)
from src.common.project import sha256_file  # noqa: E402


SEASONS = {
    "25SP": {
        "experiment_code": "XXQL2501",
        "bundle": "data/user/experiments/xxql2501_from_scratch_0_4_60cm_formalprep_20260828",
        "all_treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
        "calibration": {2, 5, 10, 13},
    },
    "26SP": {
        "experiment_code": "XXQL2601",
        "bundle": "data/user/experiments/xxql2601_from_scratch_0_4_60cm_formalprep_20260828",
        "all_treatments": list(range(1, 13)),
        "calibration": {1, 3, 9, 12},
    },
}


def _parse_candidate(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("candidate must be LABEL=PARAM_CSV")
    label, path = value.split("=", 1)
    resolved = Path(path).resolve()
    if not label.strip() or not resolved.is_file():
        raise argparse.ArgumentTypeError(f"invalid candidate: {value}")
    return label.strip(), resolved


def _role(season: str, treatment: object) -> str:
    try:
        number = int(float(treatment))
    except (TypeError, ValueError):
        return "unknown"
    return "calibration" if number in SEASONS[season]["calibration"] else "spring_validation"


def _metric_rows(candidate: str, season: str, frame: pd.DataFrame, variables: list[str]) -> list[dict]:
    rows: list[dict] = []
    frame = frame.copy()
    frame["dataset_role"] = frame["TN"].map(lambda value: _role(season, value))
    for role, group in frame.groupby("dataset_role", sort=True):
        for variable in variables:
            obs_col = f"OBS_{variable}"
            sim_col = f"SIM_{variable}"
            if obs_col not in group or sim_col not in group:
                continue
            valid = group[[obs_col, sim_col]].replace([np.inf, -np.inf], np.nan).dropna()
            # DSSAT/FileA uses -99 (and occasionally more-negative variants)
            # as a missing-value sentinel.  It must never enter RMSE/NSE as a
            # real observation; the plotting pipeline applies the same gate.
            valid = valid.loc[(valid[obs_col] > -90.0) & (valid[sim_col] > -90.0)]
            if valid.empty:
                continue
            metrics = compute_metrics(
                valid[obs_col].to_numpy(float), valid[sim_col].to_numpy(float)
            )
            metrics.update(
                candidate=candidate,
                season=season,
                dataset_role=role,
                variable=variable,
                n=len(valid),
            )
            rows.append(metrics)
    return rows


def evaluate(label: str, param_csv: Path, output_root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    run_dir = output_root / f"run_{label}"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)

    design = {
        "schema_version": 1,
        "design_id": f"e02_spring_validation_{label}_20260828",
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "deterministic spring calibration plus held-out-treatment validation",
        "bounds_id": "deterministic_candidate_evaluation",
        "observation_policy": "configs/runs/e02_from_scratch_objective_contract_20260826.csv",
        "group_policy": "configs/runs/e02_from_scratch_group_policy_20260826.csv",
        "harvest_dry_objective": {"enabled": False},
        "process_state_objective": {"enabled": False},
        "nitrogen_response_objective": {"enabled": False},
        "water_response_objective": {"enabled": False},
        "seasons": [],
    }
    for season, spec in SEASONS.items():
        bundle = ROOT / str(spec["bundle"])
        design["seasons"].append(
            {
                "season_id": season,
                "experiment_code": spec["experiment_code"],
                "bundle_path": str(spec["bundle"]),
                "bundle_manifest_sha256": sha256_file(bundle / "input_manifest.json"),
                # run_multiseason executes calibration-role seasons; this is a
                # deterministic evaluation design and does not construct Phi.
                "role": "calibration",
                "treatments": spec["all_treatments"],
            }
        )
    design_path = run_dir / "evaluation_design.json"
    design_path.write_text(json.dumps(design, indent=2) + "\n", encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    command = [
        sys.executable,
        str(ROOT / "src" / "calibration" / "run_multiseason.py"),
        "--design", str(design_path),
        "--param-csv", str(param_csv),
        "--prefix", f"eval_{label}",
        "--harvest-var", "CHPDT",
        "--keep-nitrogen-outputs",
    ]
    completed = subprocess.run(
        command, cwd=run_dir, env=env, capture_output=True, text=True
    )
    (run_dir / "evaluation.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (run_dir / "evaluation.stderr.log").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"{label} deterministic evaluation failed; see {run_dir}")

    metrics: list[dict] = []
    pairs: list[pd.DataFrame] = []
    for season in SEASONS:
        season_dir = run_dir / "_seasons" / season
        harvest = build_season_harvest_compare(season_dir, season)
        process = build_season_process_compare(season_dir, season)
        metrics.extend(_metric_rows(label, season, harvest, ["DRY_INC", "DRY_CUM", "FRESH_INC", "FRESH_CUM"]))
        metrics.extend(_metric_rows(label, season, process, ["LAID", "LWAD", "SWAD", "CHTD"]))
        for kind, frame in (("harvest", harvest), ("process", process)):
            frame = frame.copy()
            frame.insert(0, "candidate", label)
            frame.insert(1, "season", season)
            frame.insert(2, "dataset_role", frame["TN"].map(lambda value: _role(season, value)))
            frame.insert(3, "kind", kind)
            pairs.append(frame)
    return pd.DataFrame(metrics), pd.concat(pairs, ignore_index=True, sort=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", action="append", type=_parse_candidate, required=True)
    parser.add_argument(
        "--out-dir",
        default="workspace/reports/e02_formal_candidate_validation_20260828",
    )
    args = parser.parse_args()
    output_root = (ROOT / args.out_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    metric_frames = []
    pair_frames = []
    for label, param_csv in args.candidate:
        metrics, pairs = evaluate(label, param_csv, output_root)
        metric_frames.append(metrics)
        pair_frames.append(pairs)
    all_metrics = pd.concat(metric_frames, ignore_index=True)
    all_pairs = pd.concat(pair_frames, ignore_index=True, sort=False)
    all_metrics.to_csv(output_root / "metrics_by_candidate_role.csv", index=False, encoding="utf-8-sig")
    all_pairs.to_csv(output_root / "comparison_pairs.csv", index=False, encoding="utf-8-sig")
    print(all_metrics.sort_values(["dataset_role", "season", "variable", "candidate"]).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
