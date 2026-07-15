"""Replay selected Morris candidates, optionally one treatment at a time."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.sensitivity.sa_model import compute_indicators


def read_flat_manifest(path: str | Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
        if ":" not in raw_line or raw_line.lstrip().startswith("#"):
            continue
        key, value = raw_line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def read_candidate(parameter_file: str | Path, run_id: int) -> dict[str, str]:
    with Path(parameter_file).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "run_id" not in reader.fieldnames:
            raise ValueError("Morris parameter file lacks run_id")
        for row in reader:
            if int(row["run_id"]) == int(run_id):
                return {name: row[name] for name in reader.fieldnames if name != "run_id"}
    raise KeyError(f"run_id {run_id} was not found")


def batch_treatments(batch_path: str | Path) -> list[int]:
    treatments: list[int] = []
    in_table = False
    for raw_line in Path(batch_path).read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = raw_line.strip()
        if stripped.upper().startswith("@FILEX"):
            in_table = True
            continue
        if not in_table or not stripped or stripped.startswith(("!", "*", "$", "@")):
            continue
        parts = stripped.split()
        if len(parts) >= 2:
            try:
                treatments.append(int(parts[1]))
            except ValueError:
                continue
    return treatments


def write_filtered_batch(source: str | Path, destination: str | Path, treatment: int | None) -> Path:
    source_path = Path(source)
    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if treatment is None:
        shutil.copy2(source_path, destination_path)
        return destination_path

    lines = source_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    output: list[str] = []
    in_table = False
    found = False
    for raw_line in lines:
        stripped = raw_line.strip()
        if stripped.upper().startswith("@FILEX"):
            in_table = True
            output.append(raw_line)
            continue
        if not in_table or not stripped or stripped.startswith(("!", "*", "$", "@")):
            output.append(raw_line)
            continue
        parts = stripped.split()
        try:
            row_treatment = int(parts[1])
        except (IndexError, ValueError):
            output.append(raw_line)
            continue
        if row_treatment == int(treatment):
            output.append(raw_line)
            found = True
    if not found:
        raise ValueError(f"Treatment {treatment} is absent from {source_path}")
    destination_path.write_text("\n".join(output) + "\n", encoding="utf-8")
    return destination_path


def write_candidate_csv(candidate: dict[str, str], path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["name", "value"])
        writer.writerows(candidate.items())
    return destination


def replay_candidates(
    case_dir: str | Path,
    run_ids: list[int],
    *,
    out_dir: str | Path,
    treatments: list[int | None],
    execute: bool,
) -> list[dict[str, Any]]:
    case_root = Path(case_dir).resolve()
    manifest = read_flat_manifest(case_root / "run_manifest.yaml")
    parameter_file = case_root / "sa_sen_morris.sen.par.csv"
    input_dir = Path(manifest.get("input_dir", "")).resolve()
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input bundle is unavailable: {input_dir}")
    batch_source = input_dir / "DSSBatch.v48"
    if not batch_source.is_file():
        raise FileNotFoundError(batch_source)
    cultivar = manifest.get("cultivar") or "TM0008"
    obs_order = case_root / "sa_obs_order.txt"
    destination = Path(out_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for run_id in run_ids:
        candidate = read_candidate(parameter_file, run_id)
        for treatment in treatments:
            label = "all" if treatment is None else f"tn{int(treatment)}"
            replay_dir = destination / f"run_{int(run_id):04d}" / label
            replay_dir.mkdir(parents=True, exist_ok=True)
            parameter_path = write_candidate_csv(candidate, replay_dir / "sa_params.csv")
            batch_path = write_filtered_batch(batch_source, replay_dir / "DSSBatch.v48", treatment)
            result: dict[str, Any] = {
                "run_id": int(run_id),
                "treatment": treatment,
                "status": "prepared",
                "replay_dir": str(replay_dir),
            }
            if execute:
                try:
                    compute_indicators(
                        workspace_dir=str(replay_dir),
                        batch_path=str(batch_path),
                        cultivar=cultivar,
                        param_csv_path=str(parameter_path),
                        out_path=str(replay_dir / "SA_Indicators.OUT"),
                        obs_order_path=str(obs_order),
                        input_dir=str(input_dir),
                        failure_artifact_dir=str(replay_dir / "failure_artifacts"),
                    )
                    result["status"] = "success"
                except Exception as exc:
                    result.update(
                        status="model_failed",
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
            results.append(result)

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "case_dir": str(case_root),
        "execute": bool(execute),
        "results": results,
    }
    (destination / "replay_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay Morris candidates for failure attribution")
    parser.add_argument("--case-dir", required=True)
    parser.add_argument("--run-id", type=int, action="append", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--treatment", type=int, action="append")
    parser.add_argument("--split-treatments", action="store_true")
    parser.add_argument("--include-all", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    input_dir = Path(read_flat_manifest(Path(args.case_dir) / "run_manifest.yaml").get("input_dir", ""))
    available = batch_treatments(input_dir / "DSSBatch.v48")
    if args.treatment:
        treatments: list[int | None] = list(dict.fromkeys(args.treatment))
    elif args.split_treatments:
        treatments = available
    else:
        treatments = [None]
    if args.include_all and None not in treatments:
        treatments.insert(0, None)

    results = replay_candidates(
        args.case_dir,
        args.run_id,
        out_dir=args.out_dir,
        treatments=treatments,
        execute=args.execute,
    )
    failed = sum(item["status"] == "model_failed" for item in results)
    print(f"replays={len(results)} failed={failed} execute={args.execute}")
    return 1 if execute_failed(args.execute, failed) else 0


def execute_failed(execute: bool, failed: int) -> bool:
    """Return a nonzero CLI status only when an executed replay fails."""
    return bool(execute and failed)


if __name__ == "__main__":
    sys.exit(main())
