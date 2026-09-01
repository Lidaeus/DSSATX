"""Audit whether nitrogen-stress factors are active before the first 26SP harvest.

Read-only diagnostic for the v46 best71 deterministic replay.  It parses
PlantGro.OUT directly (rather than inferring stress from yield residuals) and
reports NSTD/PST1A/PST2A by treatment and date.  No bundle or objective is
modified.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd


RUN_RE = re.compile(r"\*RUN\s+(\d+)")


def parse_plantgro(path: Path) -> pd.DataFrame:
    rows: list[dict[str, float | int]] = []
    run = None
    headers: list[str] | None = None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = RUN_RE.match(raw)
        if m:
            run = int(m.group(1))
            headers = None
            continue
        if raw.startswith("@YEAR"):
            headers = raw.strip().split()
            headers[0] = "YEAR"
            continue
        if run is None or headers is None or not raw.strip():
            continue
        f = raw.split()
        if len(f) < len(headers) or not re.fullmatch(r"\d{4}", f[0]):
            continue
        try:
            row: dict[str, float | int] = {"global_run": run}
            for key, value in zip(headers, f):
                row[key] = int(value) if key in {"YEAR", "DOY", "DAS", "DAP"} else float(value)
            rows.append(row)
        except ValueError:
            continue
    if not rows:
        raise ValueError(f"no PlantGro rows parsed from {path}")
    return pd.DataFrame(rows)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--det-dir", type=Path, required=True)
    p.add_argument("--mapping-csv", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--end-doy", type=int, default=146, help="inclusive calendar DOY end (default: first harvest)")
    args = p.parse_args()
    det = args.det_dir.resolve()
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    pg = parse_plantgro(det / "PlantGro.OUT")
    run_map_path = det / "det_run_mapping.csv"
    if not run_map_path.exists():
        for parent in det.parents:
            candidate = parent / "s0_run_mapping.csv"
            if candidate.exists():
                run_map_path = candidate
                break
    mapping = pd.read_csv(run_map_path)
    if "season_id" in mapping.columns:
        mapping = mapping[mapping["season_id"].eq("26SP")]
    # PlantGro.OUT restarts run numbers at 1 for each season; join on the
    # season-local run index rather than the multiseason global index.
    mapping = mapping.rename(columns={"local_run": "season_run"})[["season_run", "treatment"]]
    mapping = mapping.rename(columns={"season_run": "global_run"})
    meta = pd.read_csv(args.mapping_csv.resolve())
    meta = meta[meta["season_id"].eq("26SP")][["treatment", "water_level", "nitrogen_level"]]
    pg = pg.merge(mapping, on="global_run", how="left", validate="many_to_one").merge(meta, on="treatment", how="left", validate="many_to_one")
    pg = pg[pg["DOY"].between(75, args.end_doy)].copy()
    cols = [c for c in ["NSTD", "PST1A", "PST2A", "KSTD", "LN%D", "SN%D"] if c in pg.columns]
    keep = ["global_run", "treatment", "water_level", "nitrogen_level", "YEAR", "DOY", "DAP"] + cols
    pg[keep].to_csv(out / "early_nstress_daily.csv", index=False, encoding="utf-8-sig")
    summary_rows = []
    for (t, w, n), g in pg.groupby(["treatment", "water_level", "nitrogen_level"], dropna=False):
        row: dict[str, object] = {"treatment": int(t), "water_level": w, "nitrogen_level": n, "n_days": int(len(g))}
        for c in cols:
            x = pd.to_numeric(g[c], errors="coerce").to_numpy(float)
            row[f"{c}_max"] = float(np.nanmax(x)) if len(x) else np.nan
            row[f"{c}_mean"] = float(np.nanmean(x)) if len(x) else np.nan
            row[f"{c}_nonzero_days"] = int(np.sum(np.isfinite(x) & (np.abs(x) > 1e-12)))
        summary_rows.append(row)
    summary = pd.DataFrame(summary_rows).sort_values("treatment")
    summary.to_csv(out / "early_nstress_by_treatment.csv", index=False, encoding="utf-8-sig")
    stress_cols = [c for c in ["NSTD", "PST1A", "PST2A"] if c in pg.columns]
    stress = pg[stress_cols].apply(pd.to_numeric, errors="coerce") if stress_cols else pd.DataFrame()
    audit = {
        "det_dir": str(det),
        "run_mapping": str(run_map_path),
        "season": "26SP",
        "date_window_doy": [75, args.end_doy],
        "treatments": int(pg["treatment"].nunique()),
        "rows": int(len(pg)),
        "stress_columns": stress_cols,
        "all_stress_values_zero": bool(stress.empty or np.all(np.isclose(stress.to_numpy(float), 0.0, atol=1e-12, equal_nan=True))),
        "max_by_stress_column": {c: float(np.nanmax(pd.to_numeric(pg[c], errors="coerce"))) for c in stress_cols},
        "first_harvest_cutoff_inclusive": 146,
    }
    (out / "early_nstress_audit.json").write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
