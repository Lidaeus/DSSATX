"""Import and audit one user-defined DSSAT experiment input bundle."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.experiment_inputs import findings_as_dicts, validate_input_bundle
from src.common.project import sha256_file


def _set_weather_coordinates(path: Path, latitude: float, longitude: float) -> None:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    for index, line in enumerate(lines):
        if line.strip().upper().startswith("@ INSI") and index + 1 < len(lines):
            parts = lines[index + 1].split()
            if len(parts) < 3:
                raise ValueError(f"Cannot parse weather site row in {path}")
            parts[1] = f"{latitude:.3f}"
            parts[2] = f"{longitude:.3f}"
            lines[index + 1] = "  " + " ".join(parts)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return
    raise ValueError(f"Cannot find @ INSI weather header in {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a versioned FileX/FileA/FileT/SOIL/weather input bundle")
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--soil", required=True)
    parser.add_argument("--weather", required=True)
    parser.add_argument("--batch", required=True)
    parser.add_argument("--experiment", required=True, help="File stem, for example XXQL2501")
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument("--site-lat", type=float, default=None)
    parser.add_argument("--site-lon", type=float, default=None)
    parser.add_argument("--out-root", default=str(PROJECT_ROOT / "data" / "user" / "experiments"))
    parser.add_argument("--derived-from-bundle", default=None)
    parser.add_argument(
        "--correction-note",
        action="append",
        default=[],
        help="Auditable description of a structural or metadata correction",
    )
    args = parser.parse_args()

    source = Path(args.source_dir).resolve()
    destination = Path(args.out_root).resolve() / args.bundle_id
    if destination.exists():
        parser.error(f"Refusing to overwrite existing bundle: {destination}")
    destination.mkdir(parents=True)
    sources = [source / f"{args.experiment}{suffix}" for suffix in (".TMX", ".TMA", ".TMT")]
    sources.extend([Path(args.soil).resolve(), Path(args.weather).resolve(), Path(args.batch).resolve()])
    for item in sources:
        if not item.is_file():
            parser.error(f"Required source missing: {item}")
        target_name = "DSSBatch.v48" if item == Path(args.batch).resolve() else item.name
        shutil.copy2(item, destination / target_name)

    metadata_corrections = []
    if (args.site_lat is None) != (args.site_lon is None):
        parser.error("--site-lat and --site-lon must be provided together")
    if args.site_lat is not None and args.site_lon is not None:
        weather_target = destination / Path(args.weather).name
        _set_weather_coordinates(weather_target, args.site_lat, args.site_lon)
        metadata_corrections.append(
            {
                "file": weather_target.name,
                "field": "weather station latitude/longitude",
                "value": [args.site_lat, args.site_lon],
                "scope": "metadata only; daily weather series unchanged",
                "authority": "user decision in project thread",
            }
        )

    summary, findings = validate_input_bundle(destination)
    files = []
    for item in sorted(path for path in destination.iterdir() if path.is_file()):
        files.append({"name": item.name, "sha256": sha256_file(item), "bytes": item.stat().st_size})
    manifest = {
        "bundle_id": args.bundle_id,
        "derived_from_bundle": args.derived_from_bundle,
        "correction_notes": args.correction_note,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_files": [str(path) for path in sources],
        "authoritative_coordinates": [args.site_lat, args.site_lon] if args.site_lat is not None else None,
        "metadata_corrections": metadata_corrections,
        "files": files,
        "summary": summary,
        "findings": findings_as_dicts(findings),
        "science_status": "fail" if any(item.severity == "error" for item in findings) else "pass_with_warnings" if findings else "pass",
    }
    (destination / "input_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"bundle": str(destination), "science_status": manifest["science_status"], "findings": manifest["findings"]}, ensure_ascii=False, indent=2))
    return 2 if manifest["science_status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
