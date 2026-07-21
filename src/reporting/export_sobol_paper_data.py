"""Freeze audited Sobol sample-size evidence for the R paper renderer.

This is intentionally a small, separate bundle.  A Sobol convergence result
that fails its prespecified threshold is useful evidence about numerical
uncertainty, but it must remain visibly marked as a current-evidence DEMO and
must not be merged with a science-validated Morris bundle by implication.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


REQUIRED_FILES = {
    "scale_rankings": "sobol_scale_rankings.csv",
    "scale_group_scores": "sobol_scale_group_scores.csv",
    "convergence_comparisons": "sobol_convergence_comparisons.csv",
    "run_scale": "sobol_run_scale.csv",
    "convergence": "sobol_convergence.json",
}
OUTPUT_METRICS_FILE = "sobol_convergence_metrics.csv"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(path: Path, required: set[str]) -> pd.DataFrame:
    try:
        frame = pd.read_csv(path)
    except (OSError, pd.errors.ParserError) as exc:
        raise ValueError(f"cannot read Sobol table: {path}") from exc
    missing = required - set(frame.columns)
    if missing or frame.empty:
        raise ValueError(f"{path.name} is empty or missing columns: {sorted(missing)}")
    return frame


def _finite(frame: pd.DataFrame, columns: list[str], source: Path, *, nonnegative: bool = False) -> None:
    for column in columns:
        values = pd.to_numeric(frame[column], errors="coerce")
        if not np.isfinite(values).all() or (nonnegative and (values < 0).any()):
            raise ValueError(f"{source.name} has invalid {column} values")
        frame[column] = values


def export_sobol_bundle(*, run_id: str, convergence_dir: Path, out_dir: Path,
                        allow_unvalidated_demo: bool = False) -> Path:
    """Validate and freeze one scheduled Sobol sample-size comparison."""
    convergence_dir = convergence_dir.resolve()
    missing = [name for name in REQUIRED_FILES.values() if not (convergence_dir / name).is_file()]
    if missing:
        raise ValueError(f"Sobol convergence directory is missing: {missing}")
    paths = {role: convergence_dir / filename for role, filename in REQUIRED_FILES.items()}
    try:
        report = json.loads(paths["convergence"].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid Sobol convergence report: {paths['convergence']}") from exc
    if report.get("run_type") != "formal_sobol_convergence":
        raise ValueError("unexpected Sobol run_type")
    # Current formal reports preserve both the planned schedule and the
    # actually executed schedule; convergence must use the latter.
    samples = report.get("executed_sample_schedule", report.get("samples"))
    if not isinstance(samples, list) or len(samples) != 2 or sorted(samples) != samples:
        raise ValueError("Sobol convergence report must describe two increasing sample sizes")

    rankings = _read_csv(paths["scale_rankings"], {"base_samples", "ranking_domain", "parameter", "score", "rank"})
    groups = _read_csv(paths["scale_group_scores"], {"base_samples", "ranking_domain", "response_group", "parameter", "group_score"})
    comparisons = _read_csv(paths["convergence_comparisons"], {"samples_a", "samples_b", "ranking_domains", "passes"})
    run_scale = _read_csv(paths["run_scale"], {"base_samples", "parameter_count", "theoretical_model_runs", "actual_model_runs"})
    _finite(rankings, ["base_samples", "score", "rank"], paths["scale_rankings"], nonnegative=True)
    _finite(groups, ["base_samples", "group_score"], paths["scale_group_scores"], nonnegative=True)
    _finite(run_scale, ["base_samples", "parameter_count", "theoretical_model_runs", "actual_model_runs"],
            paths["run_scale"], nonnegative=True)
    if sorted(rankings["base_samples"].unique().tolist()) != samples:
        raise ValueError("Sobol ranking sample sizes disagree with convergence report")
    if sorted(run_scale["base_samples"].unique().tolist()) != samples:
        raise ValueError("Sobol run scale disagrees with convergence report")
    if rankings.duplicated(["base_samples", "ranking_domain", "parameter"]).any():
        raise ValueError("Sobol ranking table has duplicate parameter rows")
    if (run_scale["actual_model_runs"] <= 0).any():
        raise ValueError("Sobol run scale contains no model runs")
    comparison_records = report.get("comparisons")
    if not isinstance(comparison_records, list) or len(comparison_records) != 1:
        raise ValueError("Sobol convergence report must contain one comparison")
    domain_records = comparison_records[0].get("ranking_domains")
    if not isinstance(domain_records, list) or not domain_records:
        raise ValueError("Sobol convergence report has no per-domain diagnostics")
    metrics = pd.DataFrame(domain_records)
    required_metrics = {"ranking_domain", "spearman", "top_k", "top_k_jaccard", "max_top_k_rank_shift", "passes"}
    if required_metrics - set(metrics.columns):
        raise ValueError("Sobol convergence report has incomplete per-domain diagnostics")
    _finite(metrics, ["spearman", "top_k", "top_k_jaccard", "max_top_k_rank_shift"],
            paths["convergence"], nonnegative=True)
    metrics.insert(0, "samples_b", comparison_records[0].get("samples_b"))
    metrics.insert(0, "samples_a", comparison_records[0].get("samples_a"))
    for name, value in (report.get("thresholds") or {}).items():
        metrics[f"threshold_{name}"] = value

    data_status = "science_validated" if bool(report.get("science_validated")) else "science_pending"
    if data_status != "science_validated" and not allow_unvalidated_demo:
        raise ValueError("Sobol convergence did not pass; pass --allow-unvalidated-demo for current-evidence figures")
    for frame in (rankings, groups, comparisons, run_scale, metrics):
        frame.insert(0, "data_status", data_status)
        frame.insert(0, "run_id", run_id)
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    output_paths: dict[str, Path] = {}
    for role, frame in (("scale_rankings", rankings), ("scale_group_scores", groups),
                        ("convergence_comparisons", comparisons), ("run_scale", run_scale)):
        path = out_dir / REQUIRED_FILES[role]
        frame.to_csv(path, index=False, encoding="utf-8")
        output_paths[role] = path
    metrics_path = out_dir / OUTPUT_METRICS_FILE
    metrics.to_csv(metrics_path, index=False, encoding="utf-8")
    output_paths["convergence_metrics"] = metrics_path
    report_path = out_dir / REQUIRED_FILES["convergence"]
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_paths["convergence"] = report_path
    manifest = {
        "schema_version": 1,
        "bundle_type": "sobol_convergence_evidence",
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_status": data_status,
        "scenario_type": "formal_sobol_sample_size_comparison",
        "renderer_contract": "r_paper_figures_v2",
        "samples": samples,
        "limitations": (
            "The prespecified N64-to-N128 rank-convergence thresholds were not met. "
            "This bundle visualises numerical uncertainty and provisional screening only; "
            "it does not support quantitative Sobol rank or interaction claims."
            if data_status != "science_validated" else
            "Sobol indices are sensitivity evidence only and do not establish parameter identifiability."
        ),
        "upstream_artifacts": [
            {"role": role, "path": str(path), "sha256": sha256_file(path)} for role, path in paths.items()
        ],
        "artifacts": [
            {"role": role, "path": path.name, "sha256": sha256_file(path)}
            for role, path in output_paths.items()
        ],
    }
    manifest_path = out_dir / "paper_data_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Freeze Sobol convergence evidence for R paper figures")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--convergence-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--allow-unvalidated-demo", action="store_true")
    args = parser.parse_args(argv)
    try:
        manifest = export_sobol_bundle(
            run_id=args.run_id, convergence_dir=Path(args.convergence_dir), out_dir=Path(args.out_dir),
            allow_unvalidated_demo=args.allow_unvalidated_demo,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
