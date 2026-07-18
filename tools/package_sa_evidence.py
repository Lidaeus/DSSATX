"""Freeze existing Morris/Sobol outputs into a citeable evidence bundle.

This tool performs no model runs and no re-analysis.  It copies only declared
result/audit artifacts and records SHA-256 hashes plus source run manifests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


PATTERNS = (
    "*morris*.csv", "*morris*.json", "*morris*.md", "*.sen.par.csv",
    "*sobol*.csv", "*sobol*.json", "*sobol*.md", "*.sobol.*",
    "run_manifest.yaml", "run_status.json", "*approval*.json", "*approval*.csv",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _files(source: Path) -> list[Path]:
    found: set[Path] = set()
    for pattern in PATTERNS:
        found.update(p for p in source.rglob(pattern) if p.is_file() and "_agents" not in p.parts)
    return sorted(found)


def package_sa_evidence(morris_run_dir: str | Path, sobol_run_dir: str | Path,
                        out_dir: str | Path, *, source_docs: list[str] | None = None) -> dict:
    sources = {"morris": Path(morris_run_dir).resolve(), "sobol": Path(sobol_run_dir).resolve()}
    for label, path in sources.items():
        if not path.is_dir():
            raise FileNotFoundError(f"{label} source directory not found: {path}")
    destination = Path(out_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for label, source in sources.items():
        paths = _files(source)
        if not paths:
            raise ValueError(f"{label} source has no recognized SA evidence artifacts: {source}")
        for path in paths:
            relative = path.relative_to(source)
            target = destination / label / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            artifacts.append({
                "role": label,
                "source": str(path),
                "path": str(target.relative_to(destination)).replace("\\", "/"),
                "sha256": _sha256(target),
            })
    for doc in source_docs or []:
        path = Path(doc).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        target = destination / "source_docs" / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        artifacts.append({"role": "source_doc", "source": str(path),
                          "path": str(target.relative_to(destination)).replace("\\", "/"),
                          "sha256": _sha256(target)})
    manifest = {
        "schema_version": 1,
        "evidence_type": "sa_morris_sobol",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "computation": "reused_existing_outputs_no_new_model_runs",
        "morris_source": str(sources["morris"]),
        "sobol_source": str(sources["sobol"]),
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "citation_status": "pending_scientific_review",
    }
    (destination / "sa_evidence_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Package existing Morris/Sobol evidence without running DSSAT")
    parser.add_argument("--morris-run-dir", required=True)
    parser.add_argument("--sobol-run-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--source-doc", action="append", default=[])
    args = parser.parse_args()
    manifest = package_sa_evidence(args.morris_run_dir, args.sobol_run_dir, args.out_dir, source_docs=args.source_doc)
    print(json.dumps({"out_dir": str(Path(args.out_dir).resolve()), "artifact_count": manifest["artifact_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

