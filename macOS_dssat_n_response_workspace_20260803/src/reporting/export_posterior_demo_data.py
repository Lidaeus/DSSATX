"""Freeze the minimal T4 posterior/equifinality evidence for R layout QA.

This is intentionally a narrow adapter, not a second analysis pipeline.  It
verifies the two upstream frozen manifests, copies only their renderer-neutral
CSV members, and writes the same hash-gated ``paper_data_manifest.json`` that
the R renderer consumes.  It never reads DSSAT or PEST++ temporary outputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


POSTERIOR_FILES = {
    "posterior_diagnostics": "posterior_diagnostics.csv",
    "spearman_correlation": "spearman_correlation.csv",
    "candidate_pairs": "candidate_pairs.csv",
}
CANDIDATE_FILES = {
    "candidate_pair_predictions": "candidate_pair_predictions.csv",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid manifest: {path}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("artifacts"), list):
        raise ValueError(f"manifest lacks an artifact list: {path}")
    return value


def _verified_members(directory: Path, manifest: dict[str, Any], required: dict[str, str]) -> dict[str, Path]:
    records = {str(item.get("role")): item for item in manifest["artifacts"]}
    missing = set(required) - set(records)
    if missing:
        raise ValueError(f"manifest is missing required artifacts: {sorted(missing)}")
    resolved: dict[str, Path] = {}
    for role, expected_name in required.items():
        item = records[role]
        relative = Path(str(item.get("path", "")))
        if relative.name != expected_name or relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe or unexpected {role} artifact path: {relative}")
        candidate = (directory / relative).resolve()
        if candidate.parent != directory.resolve() or not candidate.is_file():
            raise ValueError(f"missing frozen artifact: {candidate}")
        if sha256_file(candidate) != item.get("sha256"):
            raise ValueError(f"manifest hash mismatch: {candidate}")
        resolved[role] = candidate
    return resolved


def _read_checked(path: Path, *, run_id: str, status: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if frame.empty or not {"run_id", "data_status"}.issubset(frame.columns):
        raise ValueError(f"frozen table lacks run_id/data_status or is empty: {path.name}")
    if set(frame["run_id"].astype(str)) != {run_id}:
        raise ValueError(f"mixed or wrong run_id in {path.name}")
    if set(frame["data_status"].astype(str)) != {status}:
        raise ValueError(f"mixed or wrong data_status in {path.name}")
    return frame


def export_t4_demo_bundle(
    *, run_id: str, posterior_dir: Path, candidate_dir: Path, out_dir: Path,
    allow_unvalidated_demo: bool = False,
) -> Path:
    """Verify and freeze the T4 minimal evidence into a R-only input bundle."""
    if not allow_unvalidated_demo:
        raise ValueError("T4 tooling evidence is not science_validated; pass --allow-unvalidated-demo for layout QA")
    posterior_dir, candidate_dir = posterior_dir.resolve(), candidate_dir.resolve()
    posterior_manifest_path = posterior_dir / "posterior_results_manifest.json"
    candidate_manifest_path = candidate_dir / "candidate_prediction_manifest.json"
    posterior_manifest = _load_manifest(posterior_manifest_path)
    candidate_manifest = _load_manifest(candidate_manifest_path)
    for name, manifest in (("posterior", posterior_manifest), ("candidate", candidate_manifest)):
        if manifest.get("run_id") != run_id or manifest.get("data_status") != "tooling_demo":
            raise ValueError(f"{name} manifest is not a tooling_demo for run {run_id}")
    if candidate_manifest.get("upstream", {}).get("posterior_results_manifest_sha256") != sha256_file(posterior_manifest_path):
        raise ValueError("candidate manifest does not bind to this posterior manifest")

    posterior = _verified_members(posterior_dir, posterior_manifest, POSTERIOR_FILES)
    candidates = _verified_members(candidate_dir, candidate_manifest, CANDIDATE_FILES)
    frames = {role: _read_checked(path, run_id=run_id, status="tooling_demo") for role, path in {**posterior, **candidates}.items()}
    pair_ids = set(frames["candidate_pairs"]["pair_id"])
    replay_pair_ids = set(frames["candidate_pair_predictions"]["pair_id"])
    if not pair_ids or pair_ids != replay_pair_ids or len(pair_ids) > 3:
        raise ValueError("candidate pairs and deterministic replay pairs must match (1--3 pairs)")

    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, str]] = []
    for role, source in {**posterior, **candidates}.items():
        destination = out_dir / source.name
        shutil.copyfile(source, destination)
        artifacts.append({"role": role, "path": destination.name, "sha256": sha256_file(destination)})
    payload = {
        "schema_version": 1,
        "bundle_type": "t4_posterior_equifinality",
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_status": "legacy_layout_demo",
        "scenario_type": "demo_layout",
        "renderer_contract": "r_paper_figures_v2",
        "limitations": "Tooling-demo layout QA only; no posterior or functional-equifinality scientific claim.",
        "upstream_manifests": [
            {"role": "posterior_results", "path": str(posterior_manifest_path), "sha256": sha256_file(posterior_manifest_path)},
            {"role": "candidate_predictions", "path": str(candidate_manifest_path), "sha256": sha256_file(candidate_manifest_path)},
        ],
        "artifacts": artifacts,
    }
    manifest = out_dir / "paper_data_manifest.json"
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Freeze T4 posterior demo data for the R paper renderer")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--posterior-dir", required=True)
    parser.add_argument("--candidate-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--allow-unvalidated-demo", action="store_true")
    args = parser.parse_args(argv)
    try:
        manifest = export_t4_demo_bundle(
            run_id=args.run_id, posterior_dir=Path(args.posterior_dir), candidate_dir=Path(args.candidate_dir),
            out_dir=Path(args.out_dir), allow_unvalidated_demo=args.allow_unvalidated_demo,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
