"""Role-separated deterministic validation data for a finalized calibration.

This is a small computation/export entry point, not a plotting module. It reads
the frozen input bundle and the representative deterministic DSSAT rerun, keeps
calibration/validation/diagnostic treatments separate, and writes the canonical
comparison table plus RMSE/MAE/bias summaries. Tool-development runs require an
explicit demo flag and remain non-citable.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.calibration.design_config import load_design_config
from src.calibration.finalize_calibration import verify_calibration_artifact_manifest
from src.common.input_manifest import (
    USE_VALIDATION_AGAINST_OBSERVED_IC,
    assert_use_allowed,
    verify_manifest_integrity,
)
from src.common.project import git_metadata, sha256_file
from src.common.quality import read_flat_run_manifest_field
from src.reporting.analyze_results import (
    _infer_excode_from_filex,
    _nearest_on_or_before,
    _parse_batch_entries,
    _read_evaluate_out,
    _read_freshwt_var_by_run,
    _read_plantgro_vars_by_run,
    _read_tmt_harvest_obs,
    _read_tmt_process_obs,
    _yyddd_add_days,
)
from src.reporting.figure_data import (
    VARIABLE_SPECS,
    performance_metrics,
    validate_comparison_table,
)


def _manifest_field(path: Path, key: str) -> str:
    value = read_flat_run_manifest_field(path, key)
    return str(value or "").strip()


def _require_hash(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    actual = sha256_file(path)
    if not expected or actual.lower() != expected.lower():
        raise ValueError(
            f"{label} hash mismatch: expected {expected or 'missing'}, got {actual}"
        )


def _role_lookup(spec) -> dict[int, str]:
    roles: dict[int, str] = {}
    for role in ("calibration", "validation", "diagnostic"):
        for treatment in spec.treatment_roles.get(role, ()):  # already validated
            roles[int(treatment)] = role
    return roles


def _record(
    *,
    case: str,
    data_status: str,
    role: str,
    variable: str,
    treatment: int,
    observed: float,
    simulated: float,
    source_file: Path,
    time: float = np.nan,
    time_label: str = "Season summary",
    date_code: float = np.nan,
    harvest_number: float = np.nan,
) -> dict[str, Any]:
    spec = VARIABLE_SPECS[variable]
    doy = float(date_code % 1000) if np.isfinite(date_code) else np.nan
    year = float(2000 + int(date_code // 1000)) if np.isfinite(date_code) else np.nan
    return {
        "run_id": case,
        "data_status": data_status,
        "dataset_role": role,
        "variable": variable,
        "variable_label": spec["label"],
        "unit": spec["unit"],
        "treatment": str(int(treatment)),
        "time": time,
        "time_label": time_label,
        "observed": observed,
        "simulated": simulated,
        "source_file": str(source_file.resolve()),
        "date_code": date_code,
        "year": year,
        "doy": doy,
        "dap": np.nan,
        "harvest_number": harvest_number,
        "observed_sd": np.nan,
        "observed_se": np.nan,
        "n_rep": np.nan,
    }


def _joint_records(
    evaluate_path: Path,
    *,
    case: str,
    data_status: str,
    roles: dict[int, str],
) -> list[dict[str, Any]]:
    frame = _read_evaluate_out(str(evaluate_path))
    records: list[dict[str, Any]] = []
    for row in frame.to_dict("records"):
        try:
            treatment = int(float(row.get("TN")))
        except (TypeError, ValueError):
            continue
        role = roles.get(treatment)
        if role is None:
            raise ValueError(f"Evaluate.OUT contains undeclared treatment {treatment}")
        for variable in ("ADAP", "LAIX", "CNAM"):
            try:
                observed = float(row.get(f"{variable}M", np.nan))
                simulated = float(row.get(f"{variable}S", np.nan))
            except (TypeError, ValueError):
                continue
            records.append(_record(
                case=case, data_status=data_status, role=role, variable=variable,
                treatment=treatment, observed=observed, simulated=simulated,
                source_file=evaluate_path,
            ))
    return records


def _process_records(
    tmt_path: Path,
    plantgro_path: Path,
    entries: list[dict[str, Any]],
    *,
    case: str,
    data_status: str,
    roles: dict[int, str],
) -> list[dict[str, Any]]:
    variables = ["LAID", "LWAD", "SWAD"]
    observed = _read_tmt_process_obs(str(tmt_path), variables)
    simulated = _read_plantgro_vars_by_run(str(plantgro_path), variables)
    records: list[dict[str, Any]] = []
    for entry in entries:
        run = int(entry["run"])
        treatment = int(entry["tn"])
        role = roles.get(treatment)
        if role is None:
            raise ValueError(f"batch contains undeclared treatment {treatment}")
        by_date = simulated.get(run, {})
        available = sorted(by_date)
        for point in observed.get(treatment, []):
            date = int(point["DATE"])
            sim_day = by_date.get(date)
            if sim_day is None:
                earlier = [candidate for candidate in available if candidate <= date]
                sim_day = by_date.get(earlier[-1]) if earlier else None
            for variable in variables:
                records.append(_record(
                    case=case, data_status=data_status, role=role, variable=variable,
                    treatment=treatment, observed=float(point.get(f"OBS_{variable}", np.nan)),
                    simulated=(float(sim_day.get(variable, np.nan)) if sim_day else np.nan),
                    source_file=plantgro_path, time=float(date % 1000),
                    time_label="Day of year", date_code=float(date),
                ))
    return records


def _harvest_records(
    tmt_path: Path,
    freshwt_path: Path,
    entries: list[dict[str, Any]],
    *,
    case: str,
    data_status: str,
    roles: dict[int, str],
) -> list[dict[str, Any]]:
    observed = _read_tmt_harvest_obs(str(tmt_path))
    simulated = _read_freshwt_var_by_run(str(freshwt_path), "CHPDT")
    records: list[dict[str, Any]] = []
    for entry in entries:
        run = int(entry["run"])
        treatment = int(entry["tn"])
        role = roles.get(treatment)
        if role is None:
            raise ValueError(f"batch contains undeclared treatment {treatment}")
        previous = None
        for event in observed.get(treatment, []):
            date = int(event["DATE"])
            cumulative = _nearest_on_or_before(simulated.get(run, {}), _yyddd_add_days(date, 1))
            cumulative = float(cumulative) if cumulative is not None else np.nan
            incremental = cumulative if previous is None else cumulative - previous
            previous = cumulative
            values = (
                ("DRY_INC", float(event.get("OBS_DRY_INC", np.nan)), incremental),
                ("DRY_CUM", float(event.get("OBS_DRY_CUM", np.nan)), cumulative),
            )
            for variable, obs_value, sim_value in values:
                records.append(_record(
                    case=case, data_status=data_status, role=role, variable=variable,
                    treatment=treatment, observed=obs_value, simulated=sim_value,
                    source_file=freshwt_path, time=float(date % 1000),
                    time_label="Day of year", date_code=float(date),
                    harvest_number=float(event.get("HNO", np.nan)),
                ))
    return records


def summarize_validation_metrics(comparison: pd.DataFrame) -> pd.DataFrame:
    """Compute metrics only within a role-variable-unit stratum."""
    rows: list[dict[str, Any]] = []
    for (role, variable, unit), group in comparison.groupby(
        ["dataset_role", "variable", "unit"], sort=True
    ):
        metrics = performance_metrics(group)
        observed_range = float(group["observed"].max() - group["observed"].min())
        rows.append({
            "dataset_role": role,
            "variable": variable,
            "unit": unit,
            **metrics,
            "observed_range": observed_range,
            "nrmse_range": (
                float(metrics["rmse"] / observed_range) if observed_range > 0 else np.nan
            ),
        })
    return pd.DataFrame(rows)


def build_validation_bundle(
    run_dir: str | Path,
    case: str,
    out_dir: str | Path,
    *,
    allow_unvalidated_demo: bool = False,
) -> Path:
    run_dir = Path(run_dir).resolve()
    out_dir = Path(out_dir).resolve()
    verify_calibration_artifact_manifest(
        run_dir,
        case,
        required_rerun_outputs={"Evaluate.OUT", "PlantGro.OUT", "FreshWt.OUT"},
    )
    run_manifest = run_dir / "run_manifest.yaml"
    finalize_path = run_dir / "calibration_finalize" / "calibration_finalize.json"
    finalize = json.loads(finalize_path.read_text(encoding="utf-8"))
    if finalize.get("engineering_status") != "engineering_validated":
        raise ValueError("validation requires an engineering_validated calibration finalize")
    science_validated = (
        finalize.get("science_status") == "science_validated"
        and finalize.get("scientific_status") == "validated"
    )
    if not science_validated and not allow_unvalidated_demo:
        raise ValueError(
            "calibration is not science_validated; pass --allow-unvalidated-demo "
            "only for tooling/interface QA"
        )
    data_status = "science_validated" if science_validated else "tooling_demo"

    input_dir = Path(_manifest_field(run_manifest, "input_dir")).resolve()
    input_manifest = verify_manifest_integrity(input_dir)
    assert_use_allowed(input_manifest, use=USE_VALIDATION_AGAINST_OBSERVED_IC)
    _require_hash(
        input_dir / "input_manifest.json",
        _manifest_field(run_manifest, "input_manifest_sha256"),
        "input manifest",
    )
    design_path = Path(_manifest_field(run_manifest, "design_config")).resolve()
    _require_hash(
        design_path,
        _manifest_field(run_manifest, "design_config_sha256"),
        "design config",
    )
    stage = _manifest_field(run_manifest, "design_stage")
    design = load_design_config(design_path, stage)
    split_path = Path(design.observation["split_path"]).resolve()
    _require_hash(
        split_path,
        _manifest_field(run_manifest, "validation_split_sha256"),
        "validation split",
    )

    batch_path = run_dir / "DSSBatch.v48"
    _require_hash(batch_path, _manifest_field(run_manifest, "batch_sha256"), "batch file")
    entries = _parse_batch_entries(str(batch_path))
    if not entries:
        raise ValueError(f"no batch entries found in {batch_path}")
    excode = _infer_excode_from_filex(str(input_dir / entries[0]["filex"]))
    tmt_path = input_dir / f"{excode}.TMT"
    if not tmt_path.is_file():
        raise FileNotFoundError(f"frozen observed TMT file not found: {tmt_path}")
    rerun = run_dir / "representative_deterministic_rerun"
    roles = _role_lookup(design)
    records = []
    records.extend(_joint_records(
        rerun / "Evaluate.OUT", case=case, data_status=data_status, roles=roles
    ))
    records.extend(_process_records(
        tmt_path, rerun / "PlantGro.OUT", entries,
        case=case, data_status=data_status, roles=roles,
    ))
    records.extend(_harvest_records(
        tmt_path, rerun / "FreshWt.OUT", entries,
        case=case, data_status=data_status, roles=roles,
    ))
    comparison = validate_comparison_table(pd.DataFrame(records))
    metrics = summarize_validation_metrics(comparison)

    out_dir.mkdir(parents=True, exist_ok=True)
    comparison_path = out_dir / "comparison.csv"
    metrics_path = out_dir / "metrics_by_role_variable.csv"
    comparison.to_csv(comparison_path, index=False, encoding="utf-8")
    metrics.to_csv(metrics_path, index=False, encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": case,
        "data_status": data_status,
        "scenario_type": "actual_trial_calibration",
        "approval_scope": _manifest_field(run_manifest, "approval_scope"),
        "analysis_git": git_metadata(),
        "limitations": (
            "Single-season, complete-treatment holdout validation. Tooling-demo "
            "outputs are for interface QA only and cannot support scientific claims."
        ),
        "upstream": {
            "run_manifest_sha256": sha256_file(run_manifest),
            "calibration_artifacts_manifest_sha256": sha256_file(
                run_dir / "calibration_finalize" / "calibration_artifacts_manifest.json"
            ),
            "calibration_finalize_sha256": sha256_file(finalize_path),
            "input_manifest_sha256": sha256_file(input_dir / "input_manifest.json"),
            "validation_split_sha256": sha256_file(split_path),
        },
        "artifacts": [
            {"path": comparison_path.name, "sha256": sha256_file(comparison_path)},
            {"path": metrics_path.name, "sha256": sha256_file(metrics_path)},
        ],
    }
    manifest_path = out_dir / "validation_results_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export role-separated deterministic calibration/validation metrics"
    )
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--allow-unvalidated-demo", action="store_true")
    args = parser.parse_args(argv)
    manifest = build_validation_bundle(
        args.run_dir,
        args.case,
        args.out_dir,
        allow_unvalidated_demo=args.allow_unvalidated_demo,
    )
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
