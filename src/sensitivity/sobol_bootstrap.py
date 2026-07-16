"""Recompute PESTPP-SEN Sobol indices and estimate percentile intervals."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from src.common.project import git_metadata, sha256_file
from src.common.quality import QualityReport
from src.sensitivity.sobol_audit import read_flat_manifest


def _load_design(case_dir: Path, case: str) -> tuple[dict[str, str], pd.DataFrame, pd.DataFrame]:
    manifest = read_flat_manifest(case_dir / "run_manifest.yaml")
    samples = int(manifest.get("sobol_samples", "0") or 0)
    parameter_count = int(manifest.get("sobol_parameter_count", "0") or 0)
    parameters = pd.read_csv(case_dir / f"{case}.sobol.par.csv")
    outputs = pd.read_csv(case_dir / f"{case}.sobol.obs.csv")
    expected_rows = samples * (parameter_count + 2)
    if samples <= 0 or parameter_count <= 0 or len(parameters) != expected_rows or len(outputs) != expected_rows:
        raise ValueError("Sobol raw design does not match the manifest")
    if list(parameters.columns[:1]) != ["run_id"] or list(outputs.columns[:2]) != ["run_id", "failed_flag"]:
        raise ValueError("Unexpected Sobol raw table identifiers")
    if not parameters["run_id"].equals(outputs["run_id"]):
        raise ValueError("Sobol parameter and output run identifiers are not aligned")
    if bool((pd.to_numeric(outputs["failed_flag"], errors="coerce") != 0).any()):
        raise ValueError("Cannot bootstrap a Sobol design containing failed model runs")

    names = list(parameters.columns[1:])
    a = parameters.iloc[:samples].reset_index(drop=True)
    b = parameters.iloc[samples : 2 * samples].reset_index(drop=True)
    for index, name in enumerate(names):
        hybrid = parameters.iloc[(index + 2) * samples : (index + 3) * samples].reset_index(drop=True)
        for candidate in names:
            reference = b[candidate] if candidate == name else a[candidate]
            if not np.allclose(
                pd.to_numeric(hybrid[candidate]).to_numpy(dtype=float),
                pd.to_numeric(reference).to_numpy(dtype=float),
                rtol=0.0,
                atol=1e-12,
            ):
                raise ValueError(f"Sobol hybrid block is invalid for {name}/{candidate}")
    return manifest, parameters, outputs


def bootstrap_sobol(
    case_dir: str | Path,
    out_dir: str | Path,
    *,
    case: str = "sa_sen_sobol",
    replicates: int = 500,
    bootstrap_seed: int = 20261201,
    tolerance: float = 1e-12,
) -> QualityReport:
    root = Path(case_dir).resolve()
    destination = Path(out_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    replicates = int(replicates)
    if replicates < 20:
        raise ValueError("At least 20 bootstrap replicates are required")
    manifest, parameters, outputs = _load_design(root, case)
    samples = int(manifest["sobol_samples"])
    parameter_names = list(parameters.columns[1:])
    output_names = list(outputs.columns[2:])
    si_pest = pd.read_csv(root / f"{case}.sobol.si.csv").set_index("output")
    st_pest = pd.read_csv(root / f"{case}.sobol.sti.csv").set_index("output")
    rng = np.random.default_rng(int(bootstrap_seed))
    resample_indices = rng.integers(0, samples, size=(replicates, samples))
    rows: list[dict[str, object]] = []
    reproduced: list[bool] = []
    estimable_outputs = 0
    minimum_valid_fraction = 1.0

    for output_name in output_names:
        values = pd.to_numeric(outputs[output_name], errors="coerce").to_numpy(dtype=float)
        a = values[:samples]
        b = values[samples : 2 * samples]
        variance = float(np.var(np.concatenate([a, b]), ddof=0))
        estimable = bool(np.isfinite(variance) and variance > tolerance)
        if estimable:
            estimable_outputs += 1
        a_boot = a[resample_indices]
        b_boot = b[resample_indices]
        variance_boot = np.var(np.concatenate([a_boot, b_boot], axis=1), axis=1, ddof=0)

        for parameter_index, parameter_name in enumerate(parameter_names):
            hybrid = values[
                (parameter_index + 2) * samples : (parameter_index + 3) * samples
            ]
            if estimable:
                s1 = float(np.mean(b * (hybrid - a)) / variance)
                st = float(0.5 * np.mean((a - hybrid) ** 2) / variance)
                pest_s1 = float(si_pest.loc[output_name, parameter_name])
                pest_st = float(st_pest.loc[output_name, parameter_name])
                reproduced.append(
                    bool(
                        np.isclose(s1, pest_s1, rtol=1e-4, atol=1e-4)
                        and np.isclose(st, pest_st, rtol=1e-4, atol=1e-4)
                    )
                )
                hybrid_boot = hybrid[resample_indices]
                valid = variance_boot > tolerance
                s1_boot = np.full(replicates, np.nan)
                st_boot = np.full(replicates, np.nan)
                s1_boot[valid] = np.mean(
                    b_boot[valid] * (hybrid_boot[valid] - a_boot[valid]), axis=1
                ) / variance_boot[valid]
                st_boot[valid] = 0.5 * np.mean(
                    (a_boot[valid] - hybrid_boot[valid]) ** 2, axis=1
                ) / variance_boot[valid]
                valid_fraction = float(valid.mean())
                minimum_valid_fraction = min(minimum_valid_fraction, valid_fraction)
                s1_low, s1_high = np.nanpercentile(s1_boot, [2.5, 97.5])
                st_low, st_high = np.nanpercentile(st_boot, [2.5, 97.5])
                s1_se = float(np.nanstd(s1_boot, ddof=1))
                st_se = float(np.nanstd(st_boot, ddof=1))
            else:
                s1 = float(si_pest.loc[output_name, parameter_name])
                st = float(st_pest.loc[output_name, parameter_name])
                valid_fraction = 0.0
                s1_low = s1_high = st_low = st_high = s1_se = st_se = np.nan
            rows.append(
                {
                    "observation": output_name,
                    "parameter": str(parameter_name).upper(),
                    "base_samples": samples,
                    "estimable": estimable,
                    "S1": s1,
                    "S1_se": s1_se,
                    "S1_ci_low": s1_low,
                    "S1_ci_high": s1_high,
                    "ST": st,
                    "ST_se": st_se,
                    "ST_ci_low": st_low,
                    "ST_ci_high": st_high,
                    "bootstrap_valid_fraction": valid_fraction,
                }
            )

    result = pd.DataFrame(rows)
    result.to_csv(destination / "sobol_bootstrap_indices.csv", index=False, encoding="utf-8-sig")
    is_preflight = manifest.get("run_type") == "sensitivity_sobol_preflight_case"
    report = QualityReport(run_type="sobol_bootstrap", run_id=root.name)
    report.add(
        "process_completed",
        not result.empty,
        "Sobol raw design was reconstructed and bootstrap output was produced",
        actual=len(result),
        threshold=len(output_names) * len(parameter_names),
    )
    report.add(
        "sobol_point_reproduction",
        bool(reproduced) and all(reproduced),
        "Recomputed point estimates reproduce PESTPP-SEN indices",
        actual=sum(reproduced),
        threshold=len(reproduced),
    )
    report.add(
        "sobol_estimable_responses",
        is_preflight or estimable_outputs == len(output_names),
        (
            "Preflight records non-estimable responses without interpreting intervals"
            if is_preflight
            else "Every formal response has non-zero base-sample variance"
        ),
        actual=estimable_outputs,
        threshold="record_only_in_preflight" if is_preflight else len(output_names),
    )
    report.add(
        "sobol_bootstrap_resamples",
        is_preflight or minimum_valid_fraction >= 0.95,
        (
            "Preflight records valid bootstrap fraction without interpreting intervals"
            if is_preflight
            else "At least 95% of bootstrap resamples have non-zero response variance"
        ),
        actual=minimum_valid_fraction,
        threshold="record_only_in_preflight" if is_preflight else 0.95,
    )
    report.write(destination, stem="sobol_bootstrap_quality")
    git_info = git_metadata()
    provenance = {
        "schema_version": 1,
        "run_type": "sobol_bootstrap",
        "source_case": str(root),
        "source_pst_sha256": sha256_file(root / f"{case}.pst"),
        "source_parameter_sha256": sha256_file(root / f"{case}.sobol.par.csv"),
        "source_output_sha256": sha256_file(root / f"{case}.sobol.obs.csv"),
        "replicates": replicates,
        "bootstrap_seed": int(bootstrap_seed),
        "analysis_git_commit": git_info.get("git_commit", ""),
        "analysis_git_dirty": git_info.get("git_dirty", False),
        "estimable_response_count": estimable_outputs,
        "response_count": len(output_names),
        "science_validated": report.science_validated,
    }
    (destination / "sobol_bootstrap_manifest.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap PESTPP-SEN Sobol indices")
    parser.add_argument("--case-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--case", default="sa_sen_sobol")
    parser.add_argument("--replicates", type=int, default=500)
    parser.add_argument("--bootstrap-seed", type=int, default=20261201)
    args = parser.parse_args()
    report = bootstrap_sobol(
        args.case_dir,
        args.out_dir,
        case=args.case,
        replicates=args.replicates,
        bootstrap_seed=args.bootstrap_seed,
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if report.science_validated else 2


if __name__ == "__main__":
    raise SystemExit(main())
