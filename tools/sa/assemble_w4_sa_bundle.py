"""Assemble a W4 SA bundle for R rendering (one-off helper, not a deliverable).

Copies the existing multiseason Morris paper_data bundle, appends the W2
morris_response_effects.csv, and rewrites the manifest so R's read_sa_bundle
accepts it.  Output goes to workspace/sa/w4_bundle/ so the v4 evidence is not
overwritten (plan W0 rule 5).

This is a glue script for the W4 end-to-end validation; the W2 exporter and
the W1 contract modules are the durable deliverables.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.project import git_metadata

SRC_BUNDLE = ROOT / "workspace" / "runs" / "morris_results_stability_rerun_v1" / "paper_data_multiseason_20260722"
OUT_DIR = ROOT / "workspace" / "sa" / "w4_bundle"
EFFECTS_CSV = ROOT / "workspace" / "sa" / "morris_response_effects" / "morris_response_effects.csv"

# W2 source cases (all 3 seasons x 3 seeds).
CASES = [
    ("XXQL2501", "workspace/runs/formal_morris_repro_v4/XXQL2501/r10/seed_20260729"),
    ("XXQL2501", "workspace/runs/formal_morris_repro_v4/XXQL2501/r10/seed_20260812"),
    ("XXQL2501", "workspace/runs/formal_morris_repro_v4/XXQL2501/r10/seed_20260826"),
    ("XXQL2502", "workspace/runs/formal_morris_stability_rerun_v1/XXQL2502/r40/seed_20260729"),
    ("XXQL2502", "workspace/runs/formal_morris_stability_rerun_v1/XXQL2502/r40/seed_20260812"),
    ("XXQL2502", "workspace/runs/formal_morris_stability_rerun_v1/XXQL2502/r40/seed_20260826"),
    ("XXQL2601", "workspace/runs/formal_morris_repro_v4/XXQL2601/r10/seed_20260729"),
    ("XXQL2601", "workspace/runs/formal_morris_repro_v4/XXQL2601/r10/seed_20260812"),
    ("XXQL2601", "workspace/runs/formal_morris_repro_v4/XXQL2601/r10/seed_20260826"),
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    from tools.sa.export_morris_response_effects import export_morris_response_effects

    # Read the bundle's run_id/data_status so the effects table carries matching
    # provenance (P1#2: the R reader now enforces run_id/data_status consistency
    # across every consumed table, including effects).
    src_manifest = json.loads((SRC_BUNDLE / "paper_data_manifest.json").read_text(encoding="utf-8"))
    bundle_run_id = src_manifest["run_id"]
    bundle_data_status = src_manifest.get("data_status", "science_pending")

    # Step 1: generate the full effects table (3 seasons x 3 seeds) with the
    # bundle's run_id/data_status so the provenance gate passes.
    cases = [(s, (ROOT / d).resolve()) for s, d in CASES]
    rows, effects_manifest = export_morris_response_effects(
        bundle_run_id, cases, data_status=bundle_data_status,
    )
    EFFECTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    import csv
    with EFFECTS_CSV.open("w", encoding="utf-8", newline="") as fh:
        from tools.sa.export_morris_response_effects import OUTPUT_COLUMNS
        w = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"[1/3] effects table: {len(rows)} rows (run_id={bundle_run_id}) -> {EFFECTS_CSV}")

    # Step 2: assemble the bundle directory (copy existing + add effects).
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)
    for src in SRC_BUNDLE.iterdir():
        if src.is_file():
            shutil.copy2(src, OUT_DIR / src.name)
    shutil.copy2(EFFECTS_CSV, OUT_DIR / EFFECTS_CSV.name)
    print(f"[2/3] bundle assembled -> {OUT_DIR}")

    # Step 3: rewrite the manifest to bind the effects artifact.
    manifest_path = OUT_DIR / "paper_data_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = manifest.get("artifacts", [])
    # remove any stale effects entry, then add the fresh one
    artifacts = [a for a in artifacts if a.get("path") != EFFECTS_CSV.name]
    artifacts.append({
        "role": "morris_response_effects",
        "path": EFFECTS_CSV.name,
        "sha256": sha256_file(OUT_DIR / EFFECTS_CSV.name),
        "rows": len(rows),
    })
    manifest["artifacts"] = artifacts
    manifest["w4_note"] = ("Bundle extended with W2 morris_response_effects.csv "
                           "for FigS1b response-level mu*-sigma panel (plan §5.3).")
    manifest["w4_git"] = git_metadata()
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(f"[3/3] manifest updated: {len(artifacts)} artifacts bound")
    print(f"  seasons: {effects_manifest['seasons']}, seeds: {effects_manifest['seeds']}")
    print(f"  responses: {effects_manifest['response_count']}, params: {effects_manifest['parameter_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
