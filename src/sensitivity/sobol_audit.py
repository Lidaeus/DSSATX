"""Scientific completeness audit for PESTPP-SEN Sobol cases."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from src.common.quality import QualityReport


def read_flat_manifest(path: str | Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#") or ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path) if path.is_file() else pd.DataFrame()


def _finite_frame(frame: pd.DataFrame, excluded: set[str]) -> tuple[int, int]:
    columns = [column for column in frame.columns if str(column).strip().lower() not in excluded]
    numeric = frame[columns].apply(pd.to_numeric, errors="coerce") if columns else pd.DataFrame()
    finite = int(np.isfinite(numeric.to_numpy(dtype=float)).sum()) if not numeric.empty else 0
    return finite, int(numeric.size)


def assess_sobol_case(case_dir: str | Path, case: str = "sa_sen_sobol") -> QualityReport:
    root = Path(case_dir).resolve()
    manifest = read_flat_manifest(root / "run_manifest.yaml")
    status_path = root / "run_status.json"
    status: dict[str, Any] = (
        json.loads(status_path.read_text(encoding="utf-8")) if status_path.is_file() else {}
    )
    expected_runs = int(manifest.get("sobol_expected_model_runs", "0") or 0)
    expected_parameters = int(manifest.get("sobol_parameter_count", "0") or 0)
    expected_observations = int(manifest.get("observation_count", "0") or 0)
    report = QualityReport(run_type="sobol_run", run_id=root.name)

    rec_path = root / f"{case}.rec"
    rec_text = rec_path.read_text(encoding="utf-8", errors="ignore").lower() if rec_path.is_file() else ""
    process_completed = (
        status.get("status") == "completed" and "pestpp-sen analysis complete" in rec_text
    )
    report.add(
        "process_completed",
        process_completed,
        "PEST++ manager completed and wrote the Sobol completion marker",
        actual={"status": status.get("status"), "completion_marker": "pestpp-sen analysis complete" in rec_text},
        threshold={"status": "completed", "completion_marker": True},
    )
    report.add(
        "sobol_manifest_contract",
        manifest.get("sensitivity_method") == "sobol"
        and manifest.get("run_type") in {"sensitivity_sobol_preflight_case", "sensitivity_sobol_formal_case"}
        and expected_runs > 0
        and expected_parameters > 0
        and expected_observations > 0,
        "Run manifest contains an explicit Sobol design contract",
        actual={
            "method": manifest.get("sensitivity_method"),
            "run_type": manifest.get("run_type"),
            "expected_runs": expected_runs,
            "parameters": expected_parameters,
            "observations": expected_observations,
        },
    )

    par = _read_csv(root / f"{case}.sobol.par.csv")
    obs = _read_csv(root / f"{case}.sobol.obs.csv")
    report.add(
        "sobol_run_count",
        expected_runs > 0 and len(par) == expected_runs and len(obs) == expected_runs,
        "Parameter and simulated-observation tables contain every planned Sobol design point",
        actual={"parameter_rows": len(par), "observation_rows": len(obs)},
        threshold=expected_runs,
    )
    par_ids = par.get("run_id", pd.Series(dtype=object)).astype(str)
    obs_ids = obs.get("run_id", pd.Series(dtype=object)).astype(str)
    identifiers_valid = (
        len(par_ids) == expected_runs
        and len(obs_ids) == expected_runs
        and par_ids.is_unique
        and obs_ids.is_unique
        and set(par_ids) == set(obs_ids)
    )
    report.add(
        "sobol_run_alignment",
        identifiers_valid,
        "Sobol parameter and output rows have unique, matching run identifiers",
        actual={"parameter_unique": par_ids.nunique(), "observation_unique": obs_ids.nunique()},
        threshold=expected_runs,
    )
    failed = pd.to_numeric(obs.get("failed_flag", pd.Series(dtype=float)), errors="coerce")
    report.add(
        "sobol_no_model_failures",
        len(failed) == expected_runs and failed.notna().all() and bool((failed == 0).all()),
        "Every Sobol design point completed without a model failure",
        actual=int((failed.fillna(1) != 0).sum()),
        threshold=0,
    )
    finite_outputs, total_outputs = _finite_frame(obs, {"run_id", "failed_flag"})
    scientific_columns = [
        column for column in obs.columns if str(column).strip().lower() not in {"run_id", "failed_flag"}
    ]
    scientific_values = (
        obs[scientific_columns].apply(pd.to_numeric, errors="coerce")
        if scientific_columns
        else pd.DataFrame()
    )
    missing_sentinels = int((scientific_values == -99.0).sum().sum())
    report.add(
        "sobol_outputs_finite",
        total_outputs > 0 and finite_outputs == total_outputs and missing_sentinels == 0,
        "All simulated Sobol responses are finite and contain no DSSAT missing sentinels",
        actual={"finite": finite_outputs, "total": total_outputs, "missing_sentinels": missing_sentinels},
        threshold={"finite": total_outputs, "missing_sentinels": 0},
    )
    observed_output_count = max(len(obs.columns) - 2, 0)
    report.add(
        "sobol_output_contract",
        observed_output_count == expected_observations,
        "Simulated output table matches the declared response count",
        actual=observed_output_count,
        threshold=expected_observations,
    )

    par_columns = [column for column in par.columns if str(column).strip().lower() != "run_id"]
    report.add(
        "sobol_parameter_contract",
        len(par_columns) == expected_parameters,
        "Sobol parameter table contains exactly the approved adjustable parameters",
        actual=len(par_columns),
        threshold=expected_parameters,
    )

    si = _read_csv(root / f"{case}.sobol.si.csv")
    sti = _read_csv(root / f"{case}.sobol.sti.csv")
    index_outputs = set(si.get("output", pd.Series(dtype=str)).astype(str)) | set(
        sti.get("output", pd.Series(dtype=str)).astype(str)
    )
    expected_output_names = {
        line.strip().lower()
        for line in (root / "sa_obs_order.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    scientific_index_outputs = {name.lower() for name in index_outputs if name.lower() != "phi"}
    report.add(
        "sobol_index_output_contract",
        scientific_index_outputs == expected_output_names,
        "First-order and total-effect tables cover every declared response",
        actual=len(scientific_index_outputs),
        threshold=len(expected_output_names),
    )
    si_parameters = {str(column).strip().upper() for column in si.columns if str(column).lower() != "output"}
    sti_parameters = {str(column).strip().upper() for column in sti.columns if str(column).lower() != "output"}
    expected_parameter_names = {str(column).strip().upper() for column in par_columns}
    report.add(
        "sobol_index_parameter_contract",
        si_parameters == expected_parameter_names and sti_parameters == expected_parameter_names,
        "Sobol index tables contain exactly the approved parameters",
        actual={"si": len(si_parameters), "sti": len(sti_parameters)},
        threshold=expected_parameters,
    )
    si_finite, si_total = _finite_frame(si, {"output"})
    sti_finite, sti_total = _finite_frame(sti, {"output"})
    report.add(
        "sobol_indices_finite",
        si_total > 0 and sti_total > 0 and si_finite == si_total and sti_finite == sti_total,
        "All first-order and total-effect indices are finite",
        actual=si_finite + sti_finite,
        threshold=si_total + sti_total,
    )
    if not si.empty and not sti.empty:
        index_values = pd.concat(
            [
                si.drop(columns=["output"], errors="ignore").apply(pd.to_numeric, errors="coerce"),
                sti.drop(columns=["output"], errors="ignore").apply(pd.to_numeric, errors="coerce"),
            ],
            ignore_index=True,
        )
        nonzero = int((index_values.abs() > 1e-12).sum().sum())
    else:
        nonzero = 0
    report.add(
        "sobol_indices_non_degenerate",
        nonzero > 0,
        "At least one Sobol index is materially non-zero",
        actual=nonzero,
        threshold=1,
    )
    return report


def write_sobol_audit(
    case_dir: str | Path,
    out_dir: str | Path | None = None,
    case: str = "sa_sen_sobol",
) -> QualityReport:
    root = Path(case_dir).resolve()
    destination = Path(out_dir).resolve() if out_dir else root / "sobol_audit"
    report = assess_sobol_case(root, case=case)
    report.write(destination, stem="sobol_run_quality")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a completed PESTPP-SEN Sobol case")
    parser.add_argument("--case-dir", required=True)
    parser.add_argument("--case", default="sa_sen_sobol")
    parser.add_argument("--out-dir")
    args = parser.parse_args()
    report = write_sobol_audit(args.case_dir, args.out_dir, args.case)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if report.science_validated else 2


if __name__ == "__main__":
    raise SystemExit(main())
