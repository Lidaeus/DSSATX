"""Repair isolated failed Sobol members without mutating the source case.

The source PESTPP-SEN artifacts remain immutable.  Each failed design point is
replayed twice with the case-local frozen runtime.  Only byte-identical,
complete response vectors are admitted into a derived case, whose Sobol S1/ST
tables are recomputed from the repaired raw response matrix.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.common.project import sha256_file
from src.sensitivity.sobol_audit import read_flat_manifest, write_sobol_audit


CASE = "sa_sen_sobol"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_candidate(row: pd.Series, path: Path) -> None:
    parameters = [(str(name), row[name]) for name in row.index if name != "run_id"]
    pd.DataFrame(parameters, columns=["name", "value"]).to_csv(path, index=False)


def _read_response(path: Path, names: list[str]) -> np.ndarray:
    values: list[float] = []
    for raw in path.read_text(encoding="utf-8", errors="strict").splitlines():
        if raw.strip():
            values.append(float(raw.strip()))
    vector = np.asarray(values, dtype=float)
    if len(vector) != len(names):
        raise ValueError(f"Replay response count is {len(vector)}, expected {len(names)}: {path}")
    if not np.isfinite(vector).all():
        raise ValueError(f"Replay contains non-finite responses: {path}")
    missing = [name for name, value in zip(names, vector) if value == -99.0 and not name.lower().startswith("wn_")]
    if missing:
        raise ValueError(f"Replay contains DSSAT missing sentinels: {missing[:8]}")
    return vector


def _execute_replay(source: Path, replay_dir: Path, parameter_row: pd.Series) -> tuple[np.ndarray, dict[str, Any]]:
    replay_dir.mkdir(parents=True, exist_ok=False)
    runtime = source / "runtime"
    script = runtime / "src/sensitivity/sa_model.py"
    names = [line.strip() for line in (source / "sa_obs_order.txt").read_text(encoding="utf-8").splitlines() if line.strip()]
    parameter_path = replay_dir / "sa_params.csv"
    output_path = replay_dir / "SA_Indicators.OUT"
    _write_candidate(parameter_row, parameter_path)
    command = [
        sys.executable,
        str(script),
        "--workspace", str(replay_dir),
        "--batch", str(runtime / "input/DSSBatch.v48"),
        "--cultivar", read_flat_manifest(source / "run_manifest.yaml").get("cultivar", "TM0008"),
        "--param-csv", str(parameter_path),
        "--out", str(output_path),
        "--obs-order", str(source / "sa_obs_order.txt"),
        "--input-dir", str(runtime / "input"),
        "--output-profile", str(runtime / "config/output_profile.json"),
        "--failure-artifact-dir", str(replay_dir / "failure_artifacts"),
    ]
    completed = subprocess.run(command, cwd=source, capture_output=True, text=True, check=False)
    (replay_dir / "runner_stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (replay_dir / "runner_stderr.txt").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"Isolated replay failed with exit code {completed.returncode}: {replay_dir}")
    vector = _read_response(output_path, names)
    evidence = {
        "returncode": int(completed.returncode),
        "parameter_sha256": sha256_file(parameter_path),
        "response_sha256": sha256_file(output_path),
        "stdout_sha256": sha256_file(replay_dir / "runner_stdout.txt"),
        "stderr_sha256": sha256_file(replay_dir / "runner_stderr.txt"),
        "response_count": len(vector),
    }
    return vector, evidence


def recompute_indices(parameters: pd.DataFrame, outputs: pd.DataFrame, samples: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    parameter_names = list(parameters.columns[1:])
    output_names = list(outputs.columns[2:])
    expected = samples * (len(parameter_names) + 2)
    if len(parameters) != expected or len(outputs) != expected:
        raise ValueError(f"Sobol design has {len(outputs)} rows, expected {expected}")
    si_rows: list[dict[str, Any]] = []
    st_rows: list[dict[str, Any]] = []
    for output_name in output_names:
        values = pd.to_numeric(outputs[output_name], errors="raise").to_numpy(dtype=float)
        a = values[:samples]
        b = values[samples : 2 * samples]
        variance = float(np.var(np.concatenate([a, b]), ddof=0))
        si_row: dict[str, Any] = {"output": output_name}
        st_row: dict[str, Any] = {"output": output_name}
        for index, parameter_name in enumerate(parameter_names):
            hybrid = values[(index + 2) * samples : (index + 3) * samples]
            if variance <= 1e-12:
                s1 = st = 0.0
            else:
                s1 = float(np.mean(b * (hybrid - a)) / variance)
                st = float(0.5 * np.mean((a - hybrid) ** 2) / variance)
            si_row[parameter_name] = s1
            st_row[parameter_name] = st
        si_rows.append(si_row)
        st_rows.append(st_row)
    return pd.DataFrame(si_rows), pd.DataFrame(st_rows)


def _impact(source: Path, repaired_si: pd.DataFrame, repaired_st: pd.DataFrame, destination: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    summaries: dict[str, Any] = {}
    for label, repaired, suffix in (("S1", repaired_si, "si"), ("ST", repaired_st, "sti")):
        original = pd.read_csv(source / f"{CASE}.sobol.{suffix}.csv").set_index("output")
        current = repaired.set_index("output")
        common_outputs = original.index.intersection(current.index)
        common_parameters = original.columns.intersection(current.columns)
        delta = current.loc[common_outputs, common_parameters].astype(float) - original.loc[common_outputs, common_parameters].astype(float)
        absolute = delta.abs().to_numpy().ravel()
        summaries[label] = {
            "index_count": int(absolute.size),
            "median_absolute_change": float(np.median(absolute)),
            "p95_absolute_change": float(np.quantile(absolute, 0.95)),
            "p99_absolute_change": float(np.quantile(absolute, 0.99)),
            "maximum_absolute_change": float(np.max(absolute)),
            "material_change_count_gt_0_01": int((absolute > 0.01).sum()),
        }
        for output in common_outputs:
            for parameter in common_parameters:
                rows.append({
                    "index": label,
                    "output": output,
                    "parameter": parameter,
                    "original": float(original.loc[output, parameter]),
                    "repaired": float(current.loc[output, parameter]),
                    "absolute_change": float(abs(delta.loc[output, parameter])),
                })
    pd.DataFrame(rows).to_csv(destination / "sobol_index_changes.csv", index=False, encoding="utf-8-sig")
    return summaries


def repair_case(source_dir: str | Path, derived_dir: str | Path) -> dict[str, Any]:
    source = Path(source_dir).resolve()
    destination = Path(derived_dir).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"Derived directory must be new and empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)

    manifest = read_flat_manifest(source / "run_manifest.yaml")
    samples = int(manifest["sobol_samples"])
    parameters = pd.read_csv(source / f"{CASE}.sobol.par.csv")
    outputs = pd.read_csv(source / f"{CASE}.sobol.obs.csv")
    failed = outputs.loc[pd.to_numeric(outputs["failed_flag"], errors="raise") != 0, "run_id"].astype(int).tolist()
    if not failed:
        raise ValueError("Source Sobol case contains no failed members")
    if not parameters["run_id"].is_unique or not outputs["run_id"].is_unique:
        raise ValueError("Sobol run identifiers must be unique")

    replay_root = destination / "repair_replays"
    replay_records: list[dict[str, Any]] = []
    repaired_outputs = outputs.copy()
    response_names = list(outputs.columns[2:])
    for run_id in failed:
        match = parameters.loc[parameters["run_id"].astype(int) == run_id]
        if len(match) != 1:
            raise ValueError(f"Parameter row is not unique for failed run {run_id}")
        vectors: list[np.ndarray] = []
        attempts: list[dict[str, Any]] = []
        for repeat in (1, 2):
            vector, evidence = _execute_replay(source, replay_root / f"run_{run_id:04d}" / f"repeat_{repeat}", match.iloc[0])
            vectors.append(vector)
            attempts.append({"repeat": repeat, **evidence})
        if attempts[0]["response_sha256"] != attempts[1]["response_sha256"] or not np.array_equal(vectors[0], vectors[1]):
            raise ValueError(f"Repeated outputs are not identical for run {run_id}")
        row_index = repaired_outputs.index[repaired_outputs["run_id"].astype(int) == run_id]
        repaired_outputs.loc[row_index, response_names] = vectors[0]
        repaired_outputs.loc[row_index, "failed_flag"] = 0
        replay_records.append({
            "run_id": run_id,
            "parameters": {name: float(match.iloc[0][name]) for name in parameters.columns if name != "run_id"},
            "attempts": attempts,
            "identical_repeats": True,
        })

    repaired_si, repaired_st = recompute_indices(parameters, repaired_outputs, samples)
    copy_names = [
        f"{CASE}.pst", f"{CASE}.rec", f"{CASE}.sobol.par.csv",
        "sa_obs_order.txt", "sobol_approval.csv", "sobol_approval.json", "sobol_parameters.csv",
    ]
    for name in copy_names:
        if (source / name).is_file():
            shutil.copy2(source / name, destination / name)
    repaired_outputs.to_csv(destination / f"{CASE}.sobol.obs.csv", index=False)
    repaired_si.to_csv(destination / f"{CASE}.sobol.si.csv", index=False)
    repaired_st.to_csv(destination / f"{CASE}.sobol.sti.csv", index=False)

    source_manifest_text = (source / "run_manifest.yaml").read_text(encoding="utf-8")
    derived_run_id = destination.name
    manifest_lines = [line for line in source_manifest_text.splitlines() if not line.startswith("run_id:")]
    manifest_lines.insert(0, f"run_id: {derived_run_id}")
    manifest_lines.extend([
        "derived_case: true",
        f"derived_from: {source}",
        f"derived_from_obs_sha256: {sha256_file(source / f'{CASE}.sobol.obs.csv')}",
        f"derived_from_si_sha256: {sha256_file(source / f'{CASE}.sobol.si.csv')}",
        f"derived_from_sti_sha256: {sha256_file(source / f'{CASE}.sobol.sti.csv')}",
        "repair_method: isolated_double_replay_and_formula_recompute",
        "index_generator: tomato_cal_sobol_formula_recompute",
    ])
    (destination / "run_manifest.yaml").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    status = json.loads((source / "run_status.json").read_text(encoding="utf-8"))
    status.update({
        "run_dir": str(destination),
        "scientific_status": "pending",
        "scientific_status_error": "Derived repair awaits audit and bootstrap",
        "derived_from": str(source),
    })
    (destination / "run_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    impact = _impact(source, repaired_si, repaired_st, destination)
    repair_manifest = {
        "schema_version": 1,
        "run_type": "sobol_failed_member_repair",
        "generated_at": _utc_now(),
        "source_case": str(source),
        "derived_case": str(destination),
        "source_hashes": {
            name: sha256_file(source / name)
            for name in (f"{CASE}.pst", f"{CASE}.sobol.par.csv", f"{CASE}.sobol.obs.csv", f"{CASE}.sobol.si.csv", f"{CASE}.sobol.sti.csv")
        },
        "failed_run_ids": failed,
        "replay_count_per_member": 2,
        "replays": replay_records,
        "derived_hashes": {
            name: sha256_file(destination / name)
            for name in (f"{CASE}.sobol.obs.csv", f"{CASE}.sobol.si.csv", f"{CASE}.sobol.sti.csv")
        },
        "index_impact": impact,
    }
    (destination / "sobol_repair_manifest.json").write_text(json.dumps(repair_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    audit = write_sobol_audit(destination)
    if not audit.science_validated:
        raise RuntimeError("Derived Sobol case failed the run-quality audit")
    status.update({"scientific_status": "validated", "scientific_status_error": ""})
    (destination / "run_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return repair_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-case", required=True)
    parser.add_argument("--derived-case", required=True)
    args = parser.parse_args()
    result = repair_case(args.source_case, args.derived_case)
    print(json.dumps({
        "derived_case": result["derived_case"],
        "failed_run_ids": result["failed_run_ids"],
        "index_impact": result["index_impact"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
