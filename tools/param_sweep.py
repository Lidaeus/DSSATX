import argparse
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd

from src.common.project import WORKSPACE_DIR
from src.reporting import analyze_results as ar

WORKSPACE = str(WORKSPACE_DIR)


def _parse_grid(grid_text):
    grid_text = (grid_text or "").strip()
    if not grid_text:
        return {}
    grid = {}
    for chunk in grid_text.split(";"):
        s = chunk.strip()
        if not s:
            continue
        if "=" not in s:
            raise ValueError(f"Invalid grid item (missing '='): {s}")
        k, v = s.split("=", 1)
        key = k.strip().upper()
        vals = []
        for t in v.split(","):
            tt = t.strip()
            if not tt:
                continue
            vals.append(float(tt))
        if not vals:
            raise ValueError(f"Empty grid values for {key}")
        grid[key] = vals
    return grid


def _read_base_params(path):
    df = pd.read_csv(path)
    cols = [str(c) for c in df.columns]
    if "name" in cols and "value" in cols:
        pairs = [(str(r["name"]).strip().upper(), float(r["value"])) for _, r in df.iterrows() if str(r.get("name", "")).strip()]
    elif "Value" in cols:
        unnamed = [c for c in cols if c.lower().startswith("unnamed")]
        if not unnamed:
            raise ValueError(f"Unrecognized parameter CSV: {cols}")
        pairs = [(str(r[unnamed[0]]).strip().upper(), float(r["Value"])) for _, r in df.iterrows() if str(r.get(unnamed[0], "")).strip()]
    else:
        if len(cols) < 2:
            raise ValueError(f"Unrecognized parameter CSV: {cols}")
        pairs = [(str(r[cols[0]]).strip().upper(), float(r[cols[1]])) for _, r in df.iterrows() if str(r.get(cols[0], "")).strip()]
    out = {}
    for k, v in pairs:
        out[k] = v
    return out


def _write_param_csv(param_dict, path):
    rows = sorted(param_dict.items(), key=lambda x: x[0])
    pd.DataFrame(rows, columns=["name", "value"]).to_csv(path, index=False, encoding="utf-8-sig")


def _ensure_dir(p):
    os.makedirs(p, exist_ok=True)
    return p


def _parse_batch_entries(batch_file):
    entries = []
    with open(batch_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if (not s) or s.startswith("$") or s.startswith("@") or s.startswith("!"):
                continue
            parts = s.split()
            if not parts:
                continue
            filex = parts[0]
            tn = -99
            if len(parts) >= 2:
                try:
                    tn = int(float(parts[1]))
                except Exception:
                    tn = -99
            entries.append({"filex": filex, "TN": tn})
    for i, e in enumerate(entries, start=1):
        e["RUN"] = i
    return entries


def _read_plantgro_snapshots(plantgro_path, yyddd_targets):
    yyddd_targets = {int(k): int(v) for k, v in yyddd_targets.items()}
    if not os.path.exists(plantgro_path):
        return {}

    targets = {run: int(yyddd) for run, yyddd in yyddd_targets.items()}
    cols = ["YEAR", "DOY", "RDPD", "RWAD", "NSTD", "LN%D", "PWAD", "SWAD", "LAID"]
    snap = {}

    cur_run = None
    header = None
    idx = {}
    last_by_run = {}

    with open(plantgro_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.rstrip("\n")
            if s.startswith("*RUN"):
                m = re.match(r"^\*RUN\s+(\d+)", s)
                cur_run = int(m.group(1)) if m else None
                header = None
                idx = {}
                continue
            if cur_run is None or cur_run not in targets:
                continue
            if s.lstrip().startswith("@YEAR"):
                header = s.split()
                idx = {c: (header.index(c) if c in header else None) for c in cols}
                continue
            if not header:
                continue
            if (not s.strip()) or s.lstrip().startswith("*") or s.lstrip().startswith("!"):
                continue
            parts = s.split()
            if len(parts) < 2:
                continue
            try:
                year = int(float(parts[idx["YEAR"]])) if idx.get("YEAR") is not None else None
                doy = int(float(parts[idx["DOY"]])) if idx.get("DOY") is not None else None
            except Exception:
                continue
            if year is None or doy is None:
                continue
            yyddd = (year % 100) * 1000 + doy
            if yyddd > targets[cur_run]:
                continue
            last_by_run[cur_run] = (yyddd, parts)

    for run, (yyddd, parts) in last_by_run.items():
        row = {"YYDDD": float(yyddd)}
        for c in cols:
            if c in ("YEAR", "DOY"):
                continue
            j = idx.get(c)
            if j is None or j >= len(parts):
                row[c] = np.nan
                continue
            try:
                row[c] = float(parts[j])
            except Exception:
                row[c] = np.nan
        snap[int(run)] = row
    return snap


def _rmse_nrmse_d(obs, sim):
    return ar._rmse_nrmse_d(pd.Series(obs), pd.Series(sim))


def _metrics_from_harvest_compare(hdf):
    if hdf.empty:
        return {}
    hdf = hdf.copy()
    last = hdf.sort_values(["TN", "DATE"]).groupby("TN").tail(1)
    n, rmse, nrmse, d = _rmse_nrmse_d(last["OBS_DRY_CUM"], last["SIM_DRY_CUM"])
    return {
        "n": n,
        "rmse": rmse,
        "nrmse_pct": nrmse,
        "d_index": d,
        "mean_sim_over_obs": float(np.nanmean(last["SIM_DRY_CUM"] / last["OBS_DRY_CUM"])) if len(last) else np.nan,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base-param-csv", required=True)
    p.add_argument("--batch", required=True)
    p.add_argument("--prefix", required=True)
    p.add_argument("--grid", default="")
    p.add_argument("--out-csv", default="")
    p.add_argument("--max-cases", type=int, default=0)
    p.add_argument("--keep-runs", action="store_true")
    args = p.parse_args()

    base_param_csv = os.path.abspath(args.base_param_csv)
    batch = os.path.abspath(args.batch)
    prefix = str(args.prefix).strip()

    grid = _parse_grid(args.grid)
    if not grid:
        raise ValueError("Empty grid. Example: --grid \"NMOBMX=0.05,0.09,0.15;NVSMOB=0.2,0.38,0.6\"")

    base = _read_base_params(base_param_csv)

    keys = list(grid.keys())
    values_list = [grid[k] for k in keys]
    combos = list(itertools.product(*values_list))
    if args.max_cases and args.max_cases > 0:
        combos = combos[: int(args.max_cases)]

    out_csv = (args.out_csv or "").strip() or os.path.join(os.path.dirname(base_param_csv), f"{prefix}_sweep_summary.csv")

    results_dir = os.path.join(os.path.dirname(base_param_csv), "_sweeps", prefix)
    _ensure_dir(results_dir)

    batch_entries = _parse_batch_entries(batch)

    rows = []
    for i, vals in enumerate(combos, start=1):
        overrides = dict(zip(keys, vals))
        case_id = f"case_{i:03d}"
        case_dir = os.path.join(results_dir, case_id)
        _ensure_dir(case_dir)

        param_dict = dict(base)
        param_dict.update({k.upper(): float(v) for k, v in overrides.items()})

        case_param_csv = os.path.join(case_dir, "params.csv")
        _write_param_csv(param_dict, case_param_csv)

        batch_local = os.path.join(case_dir, "DSSBatch.v48")
        shutil.copy2(batch, batch_local)

        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "src" / "calibration" / "run_dssat.py"),
            "--param-csv",
            case_param_csv,
            "--batch",
            batch_local,
            "--harvest-var",
            "CHPDT",
        ]
        subprocess.run(cmd, cwd=case_dir, check=True)

        hcsv = ar.deterministic_harvest_compare(prefix=f"{prefix}_{case_id}", batch_file=batch_local, run_dir=case_dir)
        hdf = pd.read_csv(hcsv)
        met = _metrics_from_harvest_compare(hdf)

        yyddd_targets = {}
        for e in batch_entries:
            tn = int(e["TN"])
            run = int(e["RUN"])
            sub = hdf[hdf["TN"] == tn]
            if sub.empty:
                continue
            yyddd_targets[run] = int(sub["DATE"].max())
        snaps = _read_plantgro_snapshots(os.path.join(case_dir, "PlantGro.OUT"), yyddd_targets)

        row = {
            "case": case_id,
            **{k: float(overrides[k]) for k in keys},
            **met,
        }
        if snaps:
            for run, s in snaps.items():
                row[f"run{run}_RDPD"] = s.get("RDPD", np.nan)
                row[f"run{run}_RWAD"] = s.get("RWAD", np.nan)
                row[f"run{run}_NSTD"] = s.get("NSTD", np.nan)
                row[f"run{run}_LN%D"] = s.get("LN%D", np.nan)
                row[f"run{run}_PWAD"] = s.get("PWAD", np.nan)
        rows.append(row)

        if not args.keep_runs:
            for fn in os.listdir(case_dir):
                if fn.lower().endswith(".out"):
                    continue
                if fn.lower() in ("params.csv", "dssbatch.v48"):
                    continue
                fp = os.path.join(case_dir, fn)
                if os.path.isdir(fp):
                    continue
                try:
                    os.remove(fp)
                except Exception:
                    pass

    df = pd.DataFrame(rows)
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(out_csv)


if __name__ == "__main__":
    main()
