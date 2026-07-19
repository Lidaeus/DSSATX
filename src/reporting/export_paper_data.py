"""Export frozen, renderer-neutral data bundles for the R paper-figure pipeline.

This module intentionally does not import a plotting library. Python owns data
validation and conversion; R is the sole renderer for manuscript figures.

Scientific-validation rule: a bundle is ``science_validated`` only when the
upstream run manifest, engineering quality report, calibration finalize
artifact, and every supplied data table all agree on the same ``run_id`` and
the finalize artifact explicitly grants science validation. A
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


_FROZEN_RUN_HASH_FIELDS = (
    "input_manifest_sha256",
    "bounds_sha256",
    "observation_policy_sha256",
    "validation_split_sha256",
)


def _read_frozen_run_provenance(run_manifest_path: Path) -> dict[str, str]:
    """Read the identity hashes that make a formal calibration result reusable.

    A matching ``run_id`` is not enough: a formal paper bundle must disclose
    the frozen experiment input, bounds, observation-weight policy, and split.
    These are scalar hashes deliberately written by the calibration builder.
    """
    provenance: dict[str, str] = {}
    for field in _FROZEN_RUN_HASH_FIELDS:
        value = read_flat_run_manifest_field(run_manifest_path, field)
        if value is None or len(value) != 64 or any(char not in "0123456789abcdefABCDEF" for char in value):
            raise ValueError(f"run_manifest has no valid {field}; formal paper export is blocked")
        provenance[field] = value.lower()
    return provenance


def _write_csv(frame, path: Path) -> Path:
    frame.to_csv(path, index=False, encoding="utf-8")
    return path


def _verify_results_manifest(manifest_path: str, args) -> None:
    """Verify every provided input is a frozen results-manifest member (R0.4).

    The manifest is a JSON object with a ``files`` list of ``{path, sha256}``.
    Each provided input (comparison, phi, trajectory, treatment_metadata) must
    resolve to a manifest entry with a matching SHA-256. Prevents mixing data
    from different runs or using untracked inputs.
    """
    path = Path(manifest_path)
    if not path.is_file():
        raise ValueError(f"results manifest not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    members = {item["path"]: item["sha256"] for item in (data.get("files") or [])}
    if not members:
        raise ValueError(f"results manifest {path} lists no files")

    inputs = [
        ("comparison", args.comparison_csv),
        ("phi", args.phi_csv),
        ("trajectory", args.trajectory_run_dir),
        ("treatment_metadata", args.treatment_metadata_csv),
    ]
    for label, value in inputs:
        if not value:
            continue
        resolved = str(Path(value).resolve())
        # trajectory_run_dir is a directory — check if any member is under it.
        if label == "trajectory":
            matched = any(resolved in str(Path(m).resolve()) or str(Path(m).resolve()).startswith(resolved) for m in members)
            if not matched:
                raise ValueError(
                    f"trajectory run dir {value} is not covered by the results manifest; "
                    "mixing runs or untracked inputs is not allowed"
                )
            continue
        if resolved not in members:
            raise ValueError(
                f"{label} input {value} (resolved {resolved}) is not a member of the "
                f"results manifest; mixing runs or untracked inputs is not allowed"
            )
        actual = _sha256(Path(value))
        if actual != members[resolved]:
            raise ValueError(
                f"{label} input {value} hash mismatch: manifest {members[resolved]} != on-disk {actual}"
            )


def _resolve_upstream_validation(
    *,
    run_id: str,
    comparison: pd.DataFrame,
    run_manifest_path: Path | None,
    quality_report_path: Path | None,
    calibration_finalize_path: Path | None,
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
        "calibration_finalize": None,
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

    if calibration_finalize_path is None and quality_report_path is not None:
        candidates = (
            quality_report_path.parent / "calibration_finalize.json",
            quality_report_path.parent / "calibration_finalize" / "calibration_finalize.json",
        )
        calibration_finalize_path = next((path for path in candidates if path.is_file()), None)

    if run_manifest_path is None or quality_report_path is None or calibration_finalize_path is None:
        raise ValueError(
            "science_validated export requires --run-manifest, --quality-report "
            "and calibration_finalize.json from the same run; a data_status string in the "
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
    provenance["frozen_run_inputs"] = _read_frozen_run_provenance(run_manifest_path)

    report = load_quality_report(quality_report_path)
    if report.run_id and report.run_id != run_id:
        raise ValueError(
            f"quality_report run_id {report.run_id!r} != --run-id {run_id!r}; "
            "the quality report must come from the same run"
        )
    if report.status == "fail" or not report.process_completed:
        raise ValueError(
            "engineering quality report is failed or incomplete; formal paper export is blocked"
        )
    provenance["quality_report"] = {
        "path": str(quality_report_path),
        "sha256": _sha256(quality_report_path),
        "run_type": report.run_type,
        "status": report.status,
        "science_validated": report.science_validated,
    }

    try:
        finalize = json.loads(calibration_finalize_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid calibration_finalize.json: {calibration_finalize_path}") from exc
    finalize_case = str(finalize.get("case") or "")
    if finalize_case and finalize_case != run_id:
        raise ValueError(
            f"calibration_finalize case {finalize_case!r} != --run-id {run_id!r}; "
            "the finalize artifact must come from the same run"
        )
    if finalize.get("science_status") != "science_validated" or finalize.get("scientific_status") != "validated":
        raise ValueError(
            "calibration_finalize.json does not grant science_validated; "
            "formal paper export is blocked"
        )
    provenance["calibration_finalize"] = {
        "path": str(calibration_finalize_path),
        "sha256": _sha256(calibration_finalize_path),
        "science_status": finalize.get("science_status"),
        "scientific_status": finalize.get("scientific_status"),
    }

    validated = bool(
        report.process_completed
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
    calibration_finalize_path: Path | None = None,
    scenario_type: str | None = None,
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
        calibration_finalize_path=calibration_finalize_path,
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

    # R0.5: scenario_type distinguishes calibration-trial figures (Fig 2-5)
    # from SA figures (Fig 1/S1/S2). Only 'actual_trial_calibration' may feed
    # calibration figures; 'controlled_counterfactual_sa' feeds SA figures.
    resolved_scenario_type = scenario_type or (
        "actual_trial_calibration" if not allow_unvalidated_demo else "demo_layout"
    )

    payload: dict[str, Any] = {
        "schema_version": 2,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_status": "science_validated" if validated else "legacy_layout_demo",
        "scenario_type": resolved_scenario_type,
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
    parser.add_argument(
        "--calibration-finalize",
        help="calibration_finalize.json from the same run; the sole science-validation authority",
    )
    parser.add_argument("--out-dir", required=True)
    parser.add_argument(
        "--scenario-type",
        default=None,
        help="Scenario type tag: 'actual_trial_calibration' for Fig 2-5, "
        "'controlled_counterfactual_sa' for SA figures. If omitted, defaults "
        "to 'actual_trial_calibration' for non-demo exports.",
    )
    parser.add_argument(
        "--results-manifest",
        default=None,
        help="Frozen results manifest JSON listing allowed input files with "
        "SHA-256 hashes. If provided, every input (comparison/phi/trajectory/"
        "treatment_metadata) must be a manifest member with matching hash.",
    )
    parser.add_argument("--allow-unvalidated-demo", action="store_true")
    args = parser.parse_args(argv)

    if not args.allow_unvalidated_demo:
        missing = [
            name
            for name, value in (
                ("--run-manifest", args.run_manifest),
                ("--quality-report", args.quality_report),
            )
            if not value
        ]
        if missing:
            parser.error(
                "science_validated export requires " + " and ".join(missing)
                + " (or pass --allow-unvalidated-demo for a labelled layout preview)"
            )

    # R0.4: if a frozen results manifest is provided, every input file must be
    # a manifest member with matching SHA-256 — prevents mixing runs or using
    # untracked inputs.
    if args.results_manifest:
        try:
            _verify_results_manifest(args.results_manifest, args)
        except ValueError as exc:
            parser.error(str(exc))

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
            calibration_finalize_path=(
                Path(args.calibration_finalize) if args.calibration_finalize else None
            ),
            scenario_type=args.scenario_type,
            allow_unvalidated_demo=args.allow_unvalidated_demo,
        )
    except (ValueError, ScientificQualityError) as exc:
        parser.error(str(exc))
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
