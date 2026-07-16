"""Export frozen, renderer-neutral data bundles for the R paper-figure pipeline.

This module intentionally does not import a plotting library. Python owns data
validation and conversion; R is the sole renderer for manuscript figures.

Scientific-validation rule: a bundle is ``science_validated`` only when the
upstream run manifest, the upstream quality report, and every supplied data
table all agree on the same ``run_id`` and the quality report passes. A
``data_status`` string self-reported inside ``comparison.csv`` is *not*
sufficient — writing that string into a CSV does not constitute research
validation. The DEMO path (``--allow-unvalidated-demo``) bypasses this with a
visible watermark and a ``DEMO_`` prefix and may never be cited as a paper
figure.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.common.quality import QualityReport, ScientificQualityError, load_quality_report, read_flat_run_manifest_field
from src.reporting.figure_data import (
    align_comparison_to_trajectory,
    adapt_legacy_comparison_outputs,
    read_comparison_table,
    read_dssat_trajectories,
    read_phi_ensemble,
    read_treatment_metadata,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path) -> dict[str, str]:
    return {"path": path.name, "sha256": _sha256(path)}


def _write_csv(frame, path: Path) -> Path:
    frame.to_csv(path, index=False, encoding="utf-8")
    return path


def _resolve_upstream_validation(
    *,
    run_id: str,
    comparison: pd.DataFrame,
    run_manifest_path: Path | None,
    quality_report_path: Path | None,
    allow_unvalidated_demo: bool,
) -> tuple[bool, dict[str, Any]]:
    """Decide ``science_validated`` from upstream artifacts, not the CSV alone.

    Returns ``(validated, provenance)``. ``validated`` is True only when all of:
    - the run manifest records the same ``run_id``;
    - the quality report records the same ``run_id`` and passes its gates;
    - the comparison table's rows all self-report ``science_validated``.

    The DEMO path skips the first two and forces ``validated=False``. A
    ``data_status`` string inside the CSV is never sufficient on its own.
    """
    provenance: dict[str, Any] = {
        "run_manifest": None,
        "quality_report": None,
    }

    # Mixed run_id inside the comparison table is always rejected, even in DEMO
    # mode: a figure must never blend two runs. The CLI run_id must also match.
    table_run_ids = set(comparison["run_id"].astype(str))
    if table_run_ids and table_run_ids != {run_id}:
        extra = sorted(table_run_ids - {run_id})
        raise ValueError(
            f"comparison.csv run_id values {sorted(table_run_ids)} do not match "
            f"--run-id {run_id!r} (extras: {extra}); mixing runs is not allowed"
        )

    statuses = sorted(set(comparison["data_status"].astype(str)))
    self_reported_validated = statuses == ["science_validated"]

    if allow_unvalidated_demo:
        return False, provenance

    if run_manifest_path is None or quality_report_path is None:
        raise ValueError(
            "science_validated export requires both --run-manifest and "
            "--quality-report from the same run; a data_status string in the "
            "CSV is not sufficient. Use --allow-unvalidated-demo for a labelled "
            "layout preview."
        )

    manifest_run_id = read_flat_run_manifest_field(run_manifest_path, "run_id")
    if manifest_run_id != run_id:
        raise ValueError(
            f"run_manifest run_id {manifest_run_id!r} != --run-id {run_id!r}; "
            "the manifest must come from the same run"
        )
    provenance["run_manifest"] = {
        "path": str(run_manifest_path),
        "sha256": _sha256(run_manifest_path),
        "run_id": manifest_run_id,
    }

    report = load_quality_report(quality_report_path)
    if report.run_id and report.run_id != run_id:
        raise ValueError(
            f"quality_report run_id {report.run_id!r} != --run-id {run_id!r}; "
            "the quality report must come from the same run"
        )
    report.require_pass()
    provenance["quality_report"] = {
        "path": str(quality_report_path),
        "sha256": _sha256(quality_report_path),
        "run_type": report.run_type,
        "status": report.status,
        "science_validated": report.science_validated,
    }

    validated = bool(
        report.science_validated
        and report.process_completed
        and self_reported_validated
    )
    if report.science_validated and not self_reported_validated:
        raise ValueError(
            "Quality report passes but comparison.csv data_status is not "
            "science_validated; the table must agree with the upstream gate"
        )
    return validated, provenance


def export_bundle(
    *,
    run_id: str,
    out_dir: Path,
    comparison_csv: Path | None = None,
    legacy_results_dir: Path | None = None,
    phi_csv: Path | None = None,
    trajectory_run_dir: Path | None = None,
    treatment_metadata_csv: Path | None = None,
    run_manifest_path: Path | None = None,
    quality_report_path: Path | None = None,
    allow_unvalidated_demo: bool = False,
) -> Path:
    """Create the only data contract consumed by ``paper/R/make_all.R``."""
    if (comparison_csv is None) == (legacy_results_dir is None):
        raise ValueError("Provide exactly one of comparison_csv or legacy_results_dir")

    if comparison_csv is not None:
        comparison = read_comparison_table(comparison_csv)
        original_sources = [comparison_csv.resolve()]
    else:
        comparison = adapt_legacy_comparison_outputs(legacy_results_dir, run_id)
        original_sources = [Path(item) for item in comparison["source_file"].unique()]

    # Science-validation gate: upstream run manifest + quality report must agree
    # with the table on run_id and pass. The CSV's data_status alone is not enough.
    validated, upstream_provenance = _resolve_upstream_validation(
        run_id=run_id,
        comparison=comparison,
        run_manifest_path=run_manifest_path,
        quality_report_path=quality_report_path,
        allow_unvalidated_demo=allow_unvalidated_demo,
    )
    if not validated and not allow_unvalidated_demo:
        raise ValueError(
            "Paper-data input did not pass upstream science validation; use "
            "--allow-unvalidated-demo only for a visibly labelled layout preview"
        )

    trajectory = None
    if trajectory_run_dir is not None:
        role_by_treatment: dict[str, str] = {}
        for treatment, group in comparison.groupby(comparison["treatment"].astype(str)):
            roles = sorted(set(group["dataset_role"].astype(str)))
            if len(roles) == 1:
                role_by_treatment[str(treatment)] = roles[0]
        trajectory = read_dssat_trajectories(
            trajectory_run_dir,
            run_id=run_id,
            data_status="science_validated" if validated else "legacy_unvalidated",
            role_by_treatment=role_by_treatment,
        )
        comparison = align_comparison_to_trajectory(comparison, trajectory)
        original_sources.extend(Path(item) for item in trajectory["source_file"].unique())

    treatment_metadata = None
    if treatment_metadata_csv is not None:
        treatment_metadata = read_treatment_metadata(treatment_metadata_csv)
        original_sources.append(treatment_metadata_csv.resolve())

    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts = [_write_csv(comparison, out_dir / "comparison.csv")]
    if trajectory is not None:
        artifacts.append(_write_csv(trajectory, out_dir / "simulation_trajectory.csv"))
    if treatment_metadata is not None:
        artifacts.append(_write_csv(treatment_metadata, out_dir / "treatment_metadata.csv"))

    if phi_csv is not None:
        phi = read_phi_ensemble(phi_csv)
        # Reject a phi table that carries a different run_id than the export.
        if "run_id" in phi.columns:
            phi_run_ids = set(phi["run_id"].astype(str))
            if phi_run_ids and phi_run_ids != {run_id}:
                raise ValueError(
                    f"phi_csv run_id values {sorted(phi_run_ids)} do not match "
                    f"--run-id {run_id!r}; mixing runs is not allowed"
                )
        phi.insert(0, "data_status", "science_validated" if validated else "legacy_unvalidated")
        phi.insert(0, "run_id", run_id)
        artifacts.append(_write_csv(phi, out_dir / "phi_ensemble.csv"))
        original_sources.append(phi_csv.resolve())

    payload: dict[str, Any] = {
        "schema_version": 2,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_status": "science_validated" if validated else "legacy_layout_demo",
        "renderer_contract": "r_paper_figures_v2",
        "artifacts": [_artifact(path) for path in artifacts],
        "sources": [
            {"path": str(path), "sha256": _sha256(path)}
            for path in original_sources
            if path.is_file()
        ],
        "upstream_validation": upstream_provenance,
    }
    manifest = out_dir / "paper_data_manifest.json"
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export validated data for R paper figures")
    parser.add_argument("--run-id", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--comparison-csv")
    source.add_argument("--legacy-results-dir")
    parser.add_argument("--phi-csv")
    parser.add_argument("--trajectory-run-dir")
    parser.add_argument("--treatment-metadata-csv")
    parser.add_argument(
        "--run-manifest",
        help="run_manifest.yaml from the same run; required for science_validated export",
    )
    parser.add_argument(
        "--quality-report",
        help="quality_report.json from the same run; required for science_validated export",
    )
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--allow-unvalidated-demo", action="store_true")
    args = parser.parse_args(argv)

    if not args.allow_unvalidated_demo:
        missing = [
            name
            for name, value in (("--run-manifest", args.run_manifest), ("--quality-report", args.quality_report))
            if not value
        ]
        if missing:
            parser.error(
                "science_validated export requires " + " and ".join(missing)
                + " (or pass --allow-unvalidated-demo for a labelled layout preview)"
            )

    try:
        manifest = export_bundle(
            run_id=args.run_id,
            out_dir=Path(args.out_dir),
            comparison_csv=Path(args.comparison_csv) if args.comparison_csv else None,
            legacy_results_dir=Path(args.legacy_results_dir) if args.legacy_results_dir else None,
            phi_csv=Path(args.phi_csv) if args.phi_csv else None,
            trajectory_run_dir=(
                Path(args.trajectory_run_dir) if args.trajectory_run_dir else None
            ),
            treatment_metadata_csv=(
                Path(args.treatment_metadata_csv) if args.treatment_metadata_csv else None
            ),
            run_manifest_path=Path(args.run_manifest) if args.run_manifest else None,
            quality_report_path=Path(args.quality_report) if args.quality_report else None,
            allow_unvalidated_demo=args.allow_unvalidated_demo,
        )
    except (ValueError, ScientificQualityError) as exc:
        parser.error(str(exc))
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
