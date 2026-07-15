"""Export frozen, renderer-neutral data bundles for the R paper-figure pipeline.

This module intentionally does not import a plotting library. Python owns data
validation and conversion; R is the sole renderer for manuscript figures.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from src.reporting.figure_data import (
    adapt_legacy_comparison_outputs,
    read_comparison_table,
    read_phi_ensemble,
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


def export_bundle(
    *,
    run_id: str,
    out_dir: Path,
    comparison_csv: Path | None = None,
    legacy_results_dir: Path | None = None,
    phi_csv: Path | None = None,
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

    statuses = sorted(set(comparison["data_status"].astype(str)))
    validated = statuses == ["science_validated"]
    if not validated and not allow_unvalidated_demo:
        raise ValueError(
            "Paper-data input is not science_validated; use --allow-unvalidated-demo "
            "only for a visibly labelled layout preview"
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts = [_write_csv(comparison, out_dir / "comparison.csv")]

    if phi_csv is not None:
        phi = read_phi_ensemble(phi_csv)
        phi.insert(0, "data_status", "science_validated" if validated else "legacy_unvalidated")
        phi.insert(0, "run_id", run_id)
        artifacts.append(_write_csv(phi, out_dir / "phi_ensemble.csv"))
        original_sources.append(phi_csv.resolve())

    payload: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_status": "science_validated" if validated else "legacy_layout_demo",
        "renderer_contract": "r_paper_figures_v1",
        "artifacts": [_artifact(path) for path in artifacts],
        "sources": [
            {"path": str(path), "sha256": _sha256(path)}
            for path in original_sources
            if path.is_file()
        ],
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
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--allow-unvalidated-demo", action="store_true")
    args = parser.parse_args(argv)

    try:
        manifest = export_bundle(
            run_id=args.run_id,
            out_dir=Path(args.out_dir),
            comparison_csv=Path(args.comparison_csv) if args.comparison_csv else None,
            legacy_results_dir=Path(args.legacy_results_dir) if args.legacy_results_dir else None,
            phi_csv=Path(args.phi_csv) if args.phi_csv else None,
            allow_unvalidated_demo=args.allow_unvalidated_demo,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
