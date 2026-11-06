"""Prepare auditable S1/S2/baseline/history candidates for current-soil replay."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "workspace" / "reports" / "e02_formal_candidate_validation_20260828" / "candidates"

S1_DIR = ROOT / "workspace" / "runs" / "e02_s1_canopy_corrected_v2_0_4_60cm_100x5_20260828"
S1_CASE = "e02_s1_canopy_corrected_v2_20260828"
S2_DIR = ROOT / "workspace" / "runs" / "e02_from_scratch_s2_yield_parallel_0_4_60cm_20260827"
S2_CASE = "e02_s2_par_yield"
HISTORY = Path(
    r"D:\DSSAT48\Tomato_Cal\Workspace\Calibration_Results\stage4_full_v24_w1_only_slpf095_best_parameters_fixed.csv"
)
BOUNDS = [
    ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_s1_canopy_parallel_bounds_20260827.csv",
    ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_s2_yield_parallel_bounds_20260827.csv",
]


def _write(label: str, values: pd.Series) -> Path:
    path = OUT / f"{label}_params.csv"
    pd.DataFrame({"name": values.index, "value": values.to_numpy(float)}).to_csv(
        path, index=False, encoding="utf-8"
    )
    return path


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    s1 = pd.read_csv(S1_DIR / f"{S1_CASE}.5.par.csv").set_index("real_name")
    s2 = pd.read_csv(S2_DIR / f"{S2_CASE}.5.par.csv").set_index("real_name")
    baseline = s1.loc["base"].astype(float).copy()

    written = {
        "baseline_currentsoil": _write("baseline_currentsoil", baseline),
        "s1_best41": _write("s1_best41", s1.loc["41"].astype(float)),
        "s1_median": _write("s1_median", s1.median(axis=0, numeric_only=True)),
        "s2_best72": _write("s2_best72", s2.loc["72"].astype(float)),
        "s2_ordered51": _write("s2_ordered51", s2.loc["51"].astype(float)),
        "s2_median": _write("s2_median", s2.median(axis=0, numeric_only=True)),
    }

    history = pd.read_csv(HISTORY)
    history["name"] = history["name"].astype(str).str.strip().str.lower()
    history_values = dict(zip(history["name"], pd.to_numeric(history["value"], errors="coerce")))

    union_bounds = pd.concat([pd.read_csv(path) for path in BOUNDS], ignore_index=True)
    union_bounds["name"] = union_bounds["name"].astype(str).str.lower()
    limits = union_bounds.groupby("name").agg(lower=("lower", "min"), upper=("upper", "max"))

    exact = baseline.copy()
    compatible = baseline.copy()
    exact_overlaid = []
    compatible_overlaid = []
    incompatible = []
    for name, value in history_values.items():
        if name not in baseline.index or pd.isna(value):
            continue
        if name.startswith("soil_") or name.startswith("ic_") or name == "fl-vs":
            continue
        exact.loc[name] = float(value)
        exact_overlaid.append(name)
        if name in limits.index and limits.loc[name, "lower"] <= value <= limits.loc[name, "upper"]:
            compatible.loc[name] = float(value)
            compatible_overlaid.append(name)
        elif name in limits.index:
            incompatible.append(
                {
                    "name": name,
                    "historical_value": float(value),
                    "lower": float(limits.loc[name, "lower"]),
                    "upper": float(limits.loc[name, "upper"]),
                }
            )

    exact.loc["fl-vs"] = 100.0
    compatible.loc["fl-vs"] = 100.0
    written["history_currentsoil_exactgenetic"] = _write(
        "history_currentsoil_exactgenetic", exact
    )
    written["history_currentsoil_compatible"] = _write(
        "history_currentsoil_compatible", compatible
    )

    audit = {
        "history_source": str(HISTORY),
        "baseline_source": str(S1_DIR / f"{S1_CASE}.5.par.csv"),
        "exact_overlaid_count": len(exact_overlaid),
        "compatible_overlaid_count": len(compatible_overlaid),
        "incompatible_reverted_to_current_baseline": incompatible,
        "forced_current_conventions": {"FL-VS": 100.0, "soil_and_ic": "current bundle/baseline"},
        "candidate_files": {label: str(path) for label, path in written.items()},
    }
    (OUT / "candidate_preparation_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
