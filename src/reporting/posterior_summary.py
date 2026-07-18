"""Minimal posterior and candidate-pair export for finalized IES runs.

The public MVP intentionally exports only marginal contraction/boundary
diagnostics, Spearman relationships, and at most three distant-parameter pairs
with similar Phi. It does not expose the older PCA/VIF/clustering exploration
as part of the stable workflow, and candidate pairs are not called functional
equifinality until deterministic prediction distances have been computed.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.calibration.finalize_calibration import verify_calibration_artifact_manifest
from src.common.project import git_metadata, sha256_file
from src.reporting.equifinality import (
    _load_phi,
    compute_correlation_matrix,
    compute_posterior_diagnostics,
    detect_functional_equifinality,
    load_posterior_ensemble,
)


def select_candidate_pairs(candidates: pd.DataFrame, max_pairs: int = 3) -> pd.DataFrame:
    """Select a small deterministic set without reusing a realization."""
    columns = [
        "pair_id", "real_a", "real_b", "phi_a", "phi_b", "phi_total",
        "parameter_distance", "prediction_distance",
    ]
    if candidates.empty:
        return pd.DataFrame(columns=columns)
    if max_pairs < 1 or candidates.empty:
        return candidates.reindex(columns=columns).head(0).copy()
    ordered = candidates.sort_values(
        ["parameter_distance", "phi_total"], ascending=[False, True], kind="stable"
    )
    selected: list[pd.Series] = []
    used: set[str] = set()
    for _, row in ordered.iterrows():
        real_a = str(row["real_a"])
        real_b = str(row["real_b"])
        if real_a in used or real_b in used:
            continue
        selected.append(row)
        used.update((real_a, real_b))
        if len(selected) >= max_pairs:
            break
    if not selected:
        return candidates.head(0).copy()
    result = pd.DataFrame(selected).reset_index(drop=True)
    result["pair_id"] = range(1, len(result) + 1)
    return result


def build_posterior_bundle(
    run_dir: str | Path,
    case: str,
    out_dir: str | Path,
    *,
    allow_unvalidated_demo: bool = False,
    max_pairs: int = 3,
) -> Path:
    run_dir = Path(run_dir).resolve()
    out_dir = Path(out_dir).resolve()
    verify_calibration_artifact_manifest(run_dir, case)
    finalize_path = run_dir / "calibration_finalize" / "calibration_finalize.json"
    finalize = json.loads(finalize_path.read_text(encoding="utf-8"))
    if finalize.get("engineering_status") != "engineering_validated":
        raise ValueError("posterior export requires engineering_validated finalize")
    science_validated = (
        finalize.get("science_status") == "science_validated"
        and finalize.get("scientific_status") == "validated"
    )
    if not science_validated and not allow_unvalidated_demo:
        raise ValueError(
            "calibration is not science_validated; pass --allow-unvalidated-demo "
            "only for tooling/interface QA"
        )
    data_status = "science_validated" if science_validated else "tooling_demo"

    prior, posterior, bounds, active, all_calibrated = load_posterior_ensemble(
        run_dir, case
    )
    diagnostics = compute_posterior_diagnostics(
        prior, posterior, bounds, all_calibrated, active
    )
    correlation = compute_correlation_matrix(posterior, active)
    spearman = correlation[["parameter_a", "parameter_b", "spearman"]].copy()
    phi = _load_phi(run_dir, case)
    candidates = select_candidate_pairs(
        detect_functional_equifinality(posterior, phi, active), max_pairs=max_pairs
    )
    for frame in (diagnostics, spearman, candidates):
        frame.insert(0, "data_status", data_status)
        frame.insert(0, "run_id", case)
    candidates["classification"] = "candidate_pair_prediction_pending"

    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[tuple[str, Path]] = []
    for role, frame, name in (
        ("posterior_diagnostics", diagnostics, "posterior_diagnostics.csv"),
        ("spearman_correlation", spearman, "spearman_correlation.csv"),
        ("candidate_pairs", candidates, "candidate_pairs.csv"),
    ):
        path = out_dir / name
        frame.to_csv(path, index=False, encoding="utf-8")
        outputs.append((role, path))

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": case,
        "data_status": data_status,
        "analysis_scope": "minimal_posterior_and_candidate_pairs",
        "analysis_git": git_metadata(),
        "active_parameters": active,
        "all_calibrated_parameters": all_calibrated,
        "candidate_pair_count": len(candidates),
        "candidate_pair_status": "prediction_distance_pending",
        "limitations": (
            "IES conditional ensemble; no claim of exact Bayesian posterior. "
            "Candidate pairs are not functional-equifinal until deterministic "
            "validation/diagnostic prediction distances are available."
        ),
        "upstream": {
            "calibration_artifacts_manifest_sha256": sha256_file(
                run_dir / "calibration_finalize" / "calibration_artifacts_manifest.json"
            ),
            "calibration_finalize_sha256": sha256_file(finalize_path),
        },
        "artifacts": [
            {"role": role, "path": path.name, "sha256": sha256_file(path)}
            for role, path in outputs
        ],
    }
    manifest_path = out_dir / "posterior_results_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export minimal posterior diagnostics and candidate pairs"
    )
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--max-pairs", type=int, default=3)
    parser.add_argument("--allow-unvalidated-demo", action="store_true")
    args = parser.parse_args(argv)
    manifest = build_posterior_bundle(
        args.run_dir,
        args.case,
        args.out_dir,
        allow_unvalidated_demo=args.allow_unvalidated_demo,
        max_pairs=args.max_pairs,
    )
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
