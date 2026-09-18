#!/usr/bin/env python3
"""Promote the fixed 95%-moisture (DMC=5%) observation truth to active bundles.

The generator is the only place where values are calculated.  This script
copies the generated FileA/FileT, harvest audits and uncertainty tables into
every active season bundle, updates manifest file hashes, and writes a full
before/after audit under ``workspace/runs``.  Historical calibration run
directories are intentionally not rewritten.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "data" / "user" / "ref" / "DSSAT文件"
BUNDLES = ROOT / "data" / "user" / "experiments"
AUDIT_DIR = ROOT / "workspace" / "runs" / "fruit_moisture_95pct_dmc5pct_replacement_20260802"

SEASONS = {
    "XXQL2501": "2025春",
    "XXQL2502": "2025秋",
    "XXQL2601": "2026春",
}
COMMON = [
    "{ex}.TMA", "{ex}.TMT", "observation_uncertainty.csv",
    "fruit_quality_match_audit.csv", "FileA_values.csv", "FileT_values.csv",
    "generator_log.json", "trial_generator_log.json",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_record(name: str, path: Path, source: Path) -> dict:
    return {
        "name": name,
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "generated_by": "tools/experiments/build_trial_observations_v2_20260726.py",
        "generator_sha256": sha256(ROOT / "tools/experiments/build_trial_observations_v2_20260726.py"),
        "source_v2_dir": str(source),
    }


def update_manifest(bundle: Path, copied: list[tuple[str, Path, Path]]) -> None:
    manifest_path = bundle / "input_manifest.json"
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = {str(r.get("name")): r for r in manifest.get("files", []) if r.get("name")}
    for name, dst, src in copied:
        records[name] = file_record(name, dst, src)
    manifest["files"] = list(records.values())
    roles = manifest.setdefault("files_by_role", {})
    trial = [r for n, r in records.items() if n in [x.format(ex=manifest.get("excode", "")) for x in COMMON]
             or n in {"observation_uncertainty.csv", "fruit_quality_match_audit.csv", "FileA_values.csv", "FileT_values.csv",
                      "generator_log.json", "trial_generator_log.json", "treatment_exclusion_audit.csv"}]
    roles["generated_trial"] = trial
    manifest["summary"] = manifest.get("summary", {})
    manifest["summary"]["generated_trial_count"] = len(trial)
    manifest["summary"]["total_files"] = len(records)
    manifest["data_corrections"] = {
        "correction_id": "fixed_fruit_moisture_95pct_dmc5pct_v2_20260802",
        "moisture_fraction": 0.95,
        "dry_matter_fraction": 0.05,
        "variance_rule": "DMFR/DMC variance=0; dry variance=DMFR^2*fresh variance",
        "scope": "FileA/FileT, CHPDT/HPODW, observation uncertainty and harvest audit",
        "source_generator": "tools/experiments/build_trial_observations_v2_20260726.py",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    generated = {}
    for ex, season in SEASONS.items():
        src_dir = REF / season / "DSSAT输出_v2"
        if not src_dir.exists():
            raise FileNotFoundError(src_dir)
        names = [x.format(ex=ex) for x in COMMON]
        if ex == "XXQL2501":
            names.append("treatment_exclusion_audit.csv")
        generated[ex] = (src_dir, names)

    for bundle in sorted(p for p in BUNDLES.iterdir() if p.is_dir() and p.name.lower().startswith("xxql")):
        ex = next((code for code in SEASONS if (bundle / f"{code}.TMX").exists()), None)
        if ex is None:
            continue
        src_dir, names = generated[ex]
        copied: list[tuple[str, Path, Path]] = []
        for name in names:
            src = src_dir / name
            if not src.exists():
                continue
            dst = bundle / name
            before = sha256(dst) if dst.exists() else None
            shutil.copy2(src, dst)
            after = sha256(dst)
            copied.append((name, dst, src))
            rows.append({"bundle": bundle.name, "excode": ex, "file": name,
                         "before_sha256": before, "after_sha256": after,
                         "bytes": dst.stat().st_size, "changed": before != after})
        update_manifest(bundle, copied)

    audit = {
        "audit_id": "fixed_fruit_moisture_95pct_dmc5pct_replacement_20260802",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "contract": {"moisture_fraction": 0.95, "dry_matter_fraction": 0.05,
                     "dmfr_sd": 0.0, "dry_variance": "0.05^2 * fresh_variance"},
        "scope": "data/user/experiments active season bundles; historical workspace/runs preserved",
        "generator": "tools/experiments/build_trial_observations_v2_20260726.py",
        "rows": rows,
    }
    (AUDIT_DIR / "replacement_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    import csv
    with (AUDIT_DIR / "replacement_audit.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["bundle", "excode", "file", "before_sha256", "after_sha256", "bytes", "changed"])
        writer.writeheader(); writer.writerows(rows)
    print(json.dumps({"bundles": len({r['bundle'] for r in rows}), "files": len(rows), "audit_dir": str(AUDIT_DIR)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
