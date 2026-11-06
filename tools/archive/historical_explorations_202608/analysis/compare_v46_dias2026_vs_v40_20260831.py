"""Compare the v46 Dias-inspired deterministic candidates with v40 and earlier runs.

This is an evidence/lineage audit.  It deliberately does not rerun DSSAT or infer
causality from the custom grid score.  Outputs are written under workspace/reports.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "workspace" / "reports" / "e02_v46_dias2026_vs_v40_20260831"

RUNS = {
    "v40_best125": {
        "metrics": ROOT / "workspace/runs/e02_formal_v40_3x_yield_200x4_20260830/best_member_125_step20_deterministic_20260831/metrics_by_season_variable.csv",
        "params": ROOT / "workspace/runs/e02_formal_v40_3x_yield_200x4_20260830/best_member_125_step20_deterministic_20260831/best_member_125_params.csv",
        "manifest": ROOT / "figture/e02_formal_v40_3x_yield_best125_20260830/diagnostic_manifest.json",
        "config": ROOT / "configs/runs/e02_formal_v40_3x_yield_200x4_20260830.json",
    },
    "v46_best71": {
        "metrics": ROOT / "workspace/runs/e02_formal_v46_step20_custom26sp_20260831_200x4/best_member_71_deterministic_20260831/metrics_by_season_variable.csv",
        "params": ROOT / "workspace/runs/e02_formal_v46_step20_custom26sp_20260831_200x4/best_member_71_deterministic_20260831/best_member_71_params.csv",
        "manifest": ROOT / "figture/e02_formal_v46_step20_custom26sp_20260831_best71_20260831/diagnostic_manifest.json",
        "config": ROOT / "configs/runs/e02_formal_v46_step20_custom26sp_20260831_200x4.json",
    },
    "dias_early_relaxed": {
        "metrics": ROOT / "workspace/runs/e02_formal_v46_dias2026_early_relaxed_20260831/best_member_1_deterministic_20260831/metrics_by_season_variable.csv",
        "params": ROOT / "workspace/runs/e02_formal_v46_dias2026_early_relaxed_20260831/best_member_1_deterministic_20260831/best_member_1_params.csv",
        "manifest": ROOT / "figture/e02_formal_v46_dias2026_early_relaxed_20260831/diagnostic_manifest.json",
        "grid": ROOT / "workspace/reports/e02_v46_dias2026_early_relaxed_20260831/dias_early_relaxed_scorecard.csv",
    },
    "dias_double_n": {
        "metrics": ROOT / "workspace/runs/e02_formal_v46_dias2026_double_n_20260831/best_member_1_deterministic_20260831/metrics_by_season_variable.csv",
        "params": ROOT / "workspace/runs/e02_formal_v46_dias2026_double_n_20260831/best_member_1_deterministic_20260831/best_member_1_params.csv",
        "manifest": ROOT / "figture/e02_formal_v46_dias2026_double_n_20260831/diagnostic_manifest.json",
        "grid": ROOT / "workspace/reports/e02_v46_dias2026_double_n_20260831/dias_double_n_scorecard.csv",
    },
}

EARLIER = {
    "v31": ROOT / "figture/e02_formal_v31_balanced_best187_two_season_full_20260829/diagnostic_manifest.json",
    "v37": ROOT / "figture/e02_formal_v37_fresh_best137_20260829/diagnostic_manifest.json",
    "v38": ROOT / "figture/e02_formal_v38_scheme4_best70_20260830/diagnostic_manifest.json",
}


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_metrics(label: str, path: Path) -> pd.DataFrame:
    d = pd.read_csv(path)
    d.insert(0, "batch", label)
    return d


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    metric_frames = [read_metrics(k, v["metrics"]) for k, v in RUNS.items()]
    metrics = pd.concat(metric_frames, ignore_index=True)
    metrics.to_csv(OUT / "metric_comparison_long.csv", index=False, encoding="utf-8-sig")

    keys = ["season", "variable"]
    metric_cols = [c for c in metrics.columns if c not in ["batch", *keys]]
    wide = metrics.pivot_table(index=keys, columns="batch", values=metric_cols, aggfunc="first")
    wide.columns = [f"{a}__{b}" for a, b in wide.columns]
    wide = wide.reset_index()
    for c in [x for x in wide.columns if x.startswith("RRMSE_pct__") or x.startswith("NSE__")]:
        base = c.replace("__v40_best125", "")
        if base in wide and c != base:
            pass
    # Explicit deltas are easier to read than MultiIndex output.
    for metric in ("rrmse_pct", "nse", "d_index"):
        for b in ("v46_best71", "dias_early_relaxed", "dias_double_n"):
            col = f"{metric}__{b}"
            ref = f"{metric}__v40_best125"
            if col in wide and ref in wide:
                wide[f"delta_{metric}_{b}_vs_v40"] = wide[col] - wide[ref]
    wide.to_csv(OUT / "metric_comparison_wide.csv", index=False, encoding="utf-8-sig")

    # Parameter differences: values are candidate values, delta columns are against v40.
    p = []
    for label, spec in RUNS.items():
        d = pd.read_csv(spec["params"])[["name", "value"]].rename(columns={"value": label})
        p.append(d.set_index("name"))
    params = pd.concat(p, axis=1).reset_index()
    for b in ("v46_best71", "dias_early_relaxed", "dias_double_n"):
        params[f"delta_{b}_vs_v40"] = pd.to_numeric(params[b], errors="coerce") - pd.to_numeric(params["v40_best125"], errors="coerce")
    params.to_csv(OUT / "parameter_comparison.csv", index=False, encoding="utf-8-sig")

    lineage = {"runs": {}, "earlier_manifests": {}, "warnings": []}
    for label, spec in RUNS.items():
        man = json.loads(spec["manifest"].read_text(encoding="utf-8"))
        m = pd.read_csv(spec["metrics"])
        rec = {
            "manifest": str(spec["manifest"]),
            "source_calibration": man.get("source_calibration"),
            "best_member": man.get("best_member"),
            "manifest_best_phi": man.get("best_phi"),
            "metrics_sha256": sha256(spec["metrics"]),
            "params_sha256": sha256(spec["params"]),
            "metric_rows": int(len(m)),
            "sample_n_by_season_variable": {
                f"{season}|{variable}": int(n)
                for (season, variable), n in m.set_index(["season", "variable"])["n"].items()
            },
        }
        if "config" in spec:
            cfg = json.loads(spec["config"].read_text(encoding="utf-8"))
            rec["config"] = {k: cfg.get(k) for k in ("design_id", "bounds_id", "group_policy", "initial_condition_policy", "pest_ies")}
        if "grid" in spec:
            gd = pd.read_csv(spec["grid"])
            rec["grid_rows"] = int(len(gd))
            rec["grid_source"] = str(spec["grid"])
            rec["grid_phi_column"] = next((c for c in gd.columns if c == "phi_harvest_total_relaxed"), None)
        lineage["runs"][label] = rec
    for label, path in EARLIER.items():
        if path.exists():
            man = json.loads(path.read_text(encoding="utf-8"))
            lineage["earlier_manifests"][label] = {"manifest": str(path), "metrics_csv": man.get("metrics_csv"), "best_member": man.get("best_member")}
    # The key reproducibility warning is testable from file presence and hashes.
    v46_pst = ROOT / "workspace/runs/e02_formal_v46_step20_custom26sp_20260831_200x4/e02_formal_v46_step20_custom26sp_20260831.pst"
    for label in ("dias_early_relaxed", "dias_double_n"):
        src = Path(lineage["runs"][label]["source_calibration"]) / ("e02_formal_v46_dias2026_early_relaxed_20260831.pst" if label == "dias_early_relaxed" else "e02_formal_v46_dias2026_double_n_20260831.pst")
        if src.exists() and v46_pst.exists() and sha256(src) == sha256(v46_pst):
            lineage["warnings"].append(f"{label}: .pst hash equals v46 formal .pst; this is a deterministic grid replay, not an independent IES calibration.")
        if not (Path(lineage["runs"][label]["source_calibration"]) / ("e02_formal_v46_dias2026_early_relaxed_20260831.phi.actual.csv" if label == "dias_early_relaxed" else "e02_formal_v46_dias2026_double_n_20260831.phi.actual.csv")).exists():
            lineage["warnings"].append(f"{label}: no .phi.actual.csv in source run; manifest best_phi is custom grid Phi, not PEST++ Phi.")
    lineage["warnings"].append("v40 25SP harvest n=100 versus v46/Dias n=90; direct 25SP harvest comparison is not strictly apples-to-apples.")
    json.dump(lineage, (OUT / "lineage_audit.json").open("w", encoding="utf-8"), ensure_ascii=False, indent=2, default=str)

    # Concise machine-generated summary for the durable report.
    focus = metrics[metrics["variable"].isin(["FRESH_CUM", "LAID", "LWAD", "SWAD"])].copy()
    focus.to_csv(OUT / "focus_metrics.csv", index=False, encoding="utf-8-sig")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
