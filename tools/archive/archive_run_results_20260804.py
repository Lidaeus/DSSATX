"""Archive pre-2026-08-03 sensitivity/calibration run outputs.

This is intentionally limited to top-level run-result directories and their
diagnostic figure directories. Source code, configs, data, and parameter
registry bounds are not touched.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CUTOFF = datetime(2026, 8, 3)
AS_OF = datetime(2026, 8, 4)

SA_RE = re.compile(r"(?i)(morris|sobol|sensitivity|^sa_|_sa_|ssks|soil_sensitivity)")
CAL_RE = re.compile(
    r"(?i)(^e0[12]_.*|formal|precal|calibration|^ies|eggplant_t[89]|fwc_v2|"
    r"p2_mvp|joint|springpair|posterior|wnstress|single55|single63)"
)


def _date_tokens(name: str) -> list[datetime]:
    values = []
    for token in re.findall(r"20\d{6}", name):
        try:
            value = datetime.strptime(token, "%Y%m%d")
        except ValueError:
            continue
        if datetime(2000, 1, 1) <= value <= datetime(2099, 12, 31):
            values.append(value)
    return values


def _is_recent(path: Path) -> bool:
    dates = _date_tokens(path.name)
    if dates:
        latest = max(dates)
        if latest < CUTOFF or latest > AS_OF:
            return False
        return True
    return datetime.fromtimestamp(path.stat().st_mtime) >= CUTOFF


def _candidates(source: Path) -> list[tuple[str, Path]]:
    result: list[tuple[str, Path]] = []
    for path in source.iterdir():
        if not path.is_dir() or path.name == "_history" or _is_recent(path):
            continue
        if SA_RE.search(path.name):
            result.append(("sensitivity", path))
        elif CAL_RE.search(path.name):
            result.append(("calibration", path))
    return sorted(result, key=lambda item: (item[0], item[1].name.lower()))


def _move_group(candidates: list[tuple[str, Path]], source: Path, archive: Path, apply: bool) -> list[dict]:
    source = source.resolve()
    archive = archive.resolve()
    manifest = []
    for category, path in candidates:
        resolved = path.resolve()
        if resolved.parent != source:
            raise RuntimeError(f"refusing non-top-level source: {resolved}")
        destination = archive / category / path.name
        if destination.exists():
            raise FileExistsError(f"archive destination already exists: {destination}")
        record = {
            "category": category,
            "source": str(resolved),
            "destination": str(destination.resolve()),
            "last_write_time": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
            "action": "move" if apply else "dry_run",
        }
        manifest.append(record)
        if apply:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(resolved), str(destination))
    return manifest


def _move_extra(path: Path, destination: Path, apply: bool) -> dict | None:
    if not path.exists():
        return None
    if destination.exists():
        raise FileExistsError(f"archive destination already exists: {destination}")
    record = {
        "category": "additional_legacy_result",
        "source": str(path.resolve()),
        "destination": str(destination.resolve()),
        "last_write_time": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
        "action": "move" if apply else "dry_run",
    }
    if apply:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path.resolve()), str(destination))
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="perform the archive moves")
    args = parser.parse_args()
    run_source = ROOT / "workspace/runs"
    fig_source = ROOT / "figures/diagnostics"
    run_archive = run_source / "_history/20260804"
    fig_archive = fig_source / "_history/20260804"
    run_candidates = _candidates(run_source)
    fig_candidates = _candidates(fig_source)
    extra_candidates = [
        (ROOT / "workspace/sa", ROOT / "workspace/_history/20260804/sensitivity/workspace_sa"),
        (ROOT / "workspace/runs/average_parameter_evaluations_20260802", run_archive / "calibration/average_parameter_evaluations_20260802"),
    ]
    if not args.apply:
        print(json.dumps({
            "cutoff": CUTOFF.isoformat(),
            "run_candidates": [str(p) for _, p in run_candidates],
            "figure_candidates": [str(p) for _, p in fig_candidates],
            "extra_candidates": [str(p) for p, _ in extra_candidates if p.exists()],
        }, ensure_ascii=False, indent=2))
        return 0
    manifest_path = run_archive / "archive_manifest_20260804.json"
    prior = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else None
    manifest = prior or {
        "schema_version": 1,
        "archived_at": AS_OF.isoformat(),
        "cutoff": CUTOFF.isoformat(),
        "scope": "pre-cutoff sensitivity/calibration run outputs and diagnostic figures only",
        "kept_in_place_rule": "directories with embedded 20260803/20260804 date or no-date mtime on/after cutoff",
        "not_touched": ["src", "tools", "configs", "data", "windows", "parameter registry bounds"],
        "runs": [],
        "figures": [],
    }
    manifest["runs"].extend(_move_group(run_candidates, run_source, run_archive, True))
    manifest["figures"].extend(_move_group(fig_candidates, fig_source, fig_archive, True))
    manifest.setdefault("extras", [])
    for source, destination in extra_candidates:
        record = _move_extra(source, destination, True)
        if record is not None:
            manifest["extras"].append(record)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (fig_archive / "archive_manifest_20260804.json").write_text(
        json.dumps({"schema_version": 1, "archived_at": AS_OF.isoformat(), "source_manifest": str(manifest_path.resolve()), "figures": manifest["figures"]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "manifest": str(manifest_path.resolve()),
        "runs_moved": len(manifest["runs"]),
        "figures_moved": len(manifest["figures"]),
        "run_archive": str(run_archive.resolve()),
        "figure_archive": str(fig_archive.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
