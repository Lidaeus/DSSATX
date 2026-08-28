import argparse
import datetime
import glob
import os
import re
import shutil
import subprocess
import sys

_BOOTSTRAP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BOOTSTRAP_ROOT not in sys.path:
    sys.path.insert(0, _BOOTSTRAP_ROOT)

import numpy as np
import pandas as pd

from src.common.project import RUNS_DIR, WORKSPACE_DIR

WORKSPACE = str(WORKSPACE_DIR)
RESULTS_DIR = str(RUNS_DIR)



def _parse_batch_entries(batch_file):
    entries = []
    if not batch_file or not os.path.exists(batch_file):
        return entries

    with open(batch_file, "r") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            if s.startswith("$") or s.startswith("@") or s.startswith("!"):
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
            entries.append({"filex": filex, "tn": tn})

    for i, e in enumerate(entries, start=1):
        e["run"] = i
    return entries


def _infer_excode_from_filex(filex_path):
    if not filex_path:
        return None
    base = os.path.basename(filex_path)
    if "." in base:
        base = base.rsplit(".", 1)[0]
    return base or None


def _yyddd_add_days(yyddd, days):
    yy = int(yyddd) // 1000
    doy = int(yyddd) % 1000
    year = 2000 + yy if yy < 70 else 1900 + yy
    d0 = datetime.date(year, 1, 1) + datetime.timedelta(days=doy - 1)
    d1 = d0 + datetime.timedelta(days=int(days))
    return (d1.year % 100) * 1000 + int(d1.strftime("%j"))


def _yyddd_day_difference(start_yyddd, end_yyddd):
    """Calendar-day difference for DSSAT YYDDD codes, including year rollover."""
    def decode(value):
        yy = int(value) // 1000
        doy = int(value) % 1000
        year = 2000 + yy if yy < 70 else 1900 + yy
        return datetime.date(year, 1, 1) + datetime.timedelta(days=doy - 1)
    return (decode(end_yyddd) - decode(start_yyddd)).days


def _nearest_on_or_before(date_to_value, date):
    if not date_to_value:
        return None
    if date in date_to_value:
        return date_to_value[date]
    candidates = [d for d in date_to_value.keys() if d <= date]
    if not candidates:
        return None
    return date_to_value[max(candidates)]


def _read_freshwt_var_by_run(freshwt_path, var_name):
    if not freshwt_path or not os.path.exists(freshwt_path):
        return {}

    var_name = str(var_name).strip().upper()
    by_run = {}
    current_run = None
    header = None
    idx = None

    with open(freshwt_path, "r") as f:
        for line in f:
            s = line.rstrip("\n")
            if s.startswith("*RUN"):
                m = re.match(r"^\*RUN\s+(\d+)", s)
                current_run = int(m.group(1)) if m else None
                header = None
                idx = None
                continue

            if current_run is None:
                continue

            if s.lstrip().startswith("@YEAR"):
                header = s.split()
                try:
                    idx = header.index(var_name)
                except ValueError:
                    idx = None
                continue

            if header is None or idx is None:
                continue

            if not s.strip() or s.lstrip().startswith("*") or s.lstrip().startswith("!"):
                continue

            parts = s.split()
            if len(parts) <= idx:
                continue
            try:
                year = int(float(parts[0]))
                doy = int(float(parts[1]))
                val = float(parts[idx])
            except Exception:
                continue
            date = (year % 100) * 1000 + doy
            by_run.setdefault(current_run, {})[date] = val

    return by_run


def _read_tmt_harvest_obs(tmt_path):
    if not tmt_path or not os.path.exists(tmt_path):
        return {}

    header = None
    rows = []
    with open(tmt_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.rstrip("\n")
            if not s.strip():
                continue
            if s.lstrip().startswith("@TRNO"):
                header = s.split()
                continue
            if header is None:
                continue
            if s.startswith("*") or s.lstrip().startswith("@"): 
                continue
            parts = s.split()
            if len(parts) < 2:
                continue
            if len(parts) < len(header):
                parts += ["-99"] * (len(header) - len(parts))
            row = dict(zip(header, parts[: len(header)]))
            rows.append(row)

    def _as_int(v, default=-99):
        try:
            return int(float(v))
        except Exception:
            return default

    def _as_float(v, default=-99.0):
        try:
            return float(v)
        except Exception:
            return default

    by_tn = {}
    for r in rows:
        tn = _as_int(r.get("@TRNO"), default=-99)
        date = _as_int(r.get("DATE"), default=-99)
        if tn <= 0 or date <= 0:
            continue

        hfpow = _as_float(r.get("HFPOW"), default=-99.0)
        chfpw = _as_float(r.get("CHFPW"), default=-99.0)
        hpodw = _as_float(r.get("HPODW"), default=-99.0)
        chpdt = _as_float(r.get("CHPDT"), default=-99.0)
        pwad = _as_float(r.get("PWAD"), default=-99.0)

        if all(v == -99.0 for v in [hfpow, chfpw, hpodw, chpdt, pwad]):
            continue

        by_tn.setdefault(tn, []).append(
            {
                "date": date,
                "HFPOW": hfpow,
                "CHFPW": chfpw,
                "HPODW": hpodw,
                "CHPDT": chpdt,
                "PWAD": pwad,
            }
        )

    out = {}
    for tn, evs in by_tn.items():
        evs_sorted = sorted(evs, key=lambda x: x["date"])
        dry_cum = 0.0
        fresh_cum = 0.0
        rows_out = []
        for i, e in enumerate(evs_sorted, start=1):
            date = int(e["date"])

            if e["CHPDT"] != -99.0:
                obs_dry_cum = float(e["CHPDT"])
                # FileT commonly stores cumulative harvested dry weight only.
                # Keep reporting consistent with build_pest/run_dssat by
                # deriving the event increment from consecutive cumulative
                # observations when HPODW is absent.
                obs_dry_inc = (
                    float(e["HPODW"])
                    if e["HPODW"] != -99.0
                    else float(obs_dry_cum - dry_cum)
                )
                dry_cum = obs_dry_cum
            else:
                if e["HPODW"] != -99.0:
                    inc = e["HPODW"]
                elif e["PWAD"] != -99.0:
                    inc = e["PWAD"]
                else:
                    inc = 0.0
                dry_cum += float(inc)
                obs_dry_cum = float(dry_cum)
                obs_dry_inc = float(inc)

            if e["CHFPW"] != -99.0:
                obs_fresh_cum = float(e["CHFPW"])
                obs_fresh_inc = (
                    float(e["HFPOW"])
                    if e["HFPOW"] != -99.0
                    else float(obs_fresh_cum - fresh_cum)
                )
                fresh_cum = obs_fresh_cum
            else:
                inc = 0.0 if e["HFPOW"] == -99.0 else e["HFPOW"]
                fresh_cum += float(inc)
                obs_fresh_cum = float(fresh_cum)
                obs_fresh_inc = float(inc)

            rows_out.append(
                {
                    "HNO": i,
                    "DATE": date,
                    "OBS_DRY_INC": obs_dry_inc,
                    "OBS_DRY_CUM": obs_dry_cum,
                    "OBS_FRESH_INC": obs_fresh_inc,
                    "OBS_FRESH_CUM": obs_fresh_cum,
                }
            )

        out[tn] = rows_out
    return out


def _read_tmt_process_obs(tmt_path, var_names):
    if not tmt_path or not os.path.exists(tmt_path):
        return {}

    want = [str(v).strip().upper() for v in (var_names or []) if str(v).strip()]
    if not want:
        return {}

    header = None
    rows = []
    with open(tmt_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.rstrip("\n")
            if not s.strip():
                continue
            if s.lstrip().startswith("@TRNO"):
                header = s.split()
                continue
            if header is None:
                continue
            if s.startswith("*") or s.lstrip().startswith("@"):
                continue
            parts = s.split()
            if len(parts) < 2:
                continue
            if len(parts) < len(header):
                parts += ["-99"] * (len(header) - len(parts))
            row = dict(zip(header, parts[: len(header)]))
            rows.append(row)

    def _as_int(v, default=-99):
        try:
            return int(float(v))
        except Exception:
            return default

    def _as_float(v, default=-99.0):
        try:
            return float(v)
        except Exception:
            return default

    by_tn = {}
    for r in rows:
        tn = _as_int(r.get("@TRNO"), default=-99)
        date = _as_int(r.get("DATE"), default=-99)
        if tn <= 0 or date <= 0:
            continue

        vals = {}
        any_ok = False
        for v in want:
            raw = r.get(v)
            val = _as_float(raw, default=-99.0)
            vals[v] = val
            if val != -99.0:
                any_ok = True
        if not any_ok:
            continue

        by_tn.setdefault(tn, []).append({"DATE": int(date), **{f"OBS_{k}": float(vals[k]) for k in want}})

    out = {}
    for tn, pts in by_tn.items():
        out[tn] = sorted(pts, key=lambda x: x["DATE"])
    return out


def _read_plantgro_vars_by_run(plantgro_path, var_names):
    if not plantgro_path or not os.path.exists(plantgro_path):
        return {}

    var_names = [v for v in (var_names or []) if v]
    if not var_names:
        return {}

    by_run = {}
    current_run = None
    header = None
    idx_map = None

    with open(plantgro_path, "r") as f:
        for line in f:
            s = line.rstrip("\n")
            if s.startswith("*RUN"):
                m = re.match(r"^\*RUN\s+(\d+)", s)
                current_run = int(m.group(1)) if m else None
                header = None
                idx_map = None
                continue

            if current_run is None:
                continue

            if s.lstrip().startswith("@YEAR"):
                header = s.split()
                idx_map = {}
                for v in var_names:
                    try:
                        idx_map[v] = header.index(v)
                    except ValueError:
                        idx_map[v] = None
                continue

            if header is None or idx_map is None:
                continue

            if not s.strip() or s.lstrip().startswith("*") or s.lstrip().startswith("!"):
                continue

            parts = s.split()
            try:
                year = int(float(parts[0]))
                doy = int(float(parts[1]))
            except Exception:
                continue

            date = (year % 100) * 1000 + doy
            run_day = by_run.setdefault(current_run, {}).setdefault(date, {})
            for v, idx in idx_map.items():
                if idx is None or len(parts) <= idx:
                    continue
                try:
                    run_day[v] = float(parts[idx])
                except Exception:
                    continue

    return by_run


def deterministic_process_compare(prefix, batch_file, var_names=None, run_dir=None):
    ensure_results_dir()
    entries = _parse_batch_entries(batch_file)
    if not entries:
        raise ValueError(f"No batch entries found in {batch_file}")

    filex0 = entries[0]["filex"]
    filex_abs = filex0 if os.path.isabs(filex0) else os.path.join(WORKSPACE, filex0)
    filex_dir = os.path.dirname(os.path.abspath(filex_abs))
    excode = _infer_excode_from_filex(filex_abs)
    tmt_path = os.path.join(filex_dir, f"{excode}.TMT") if excode else None

    plantgro_candidates = []
    if run_dir:
        plantgro_candidates.append(os.path.join(run_dir, "PlantGro.OUT"))
    plantgro_candidates.extend(
        [
            os.path.join(WORKSPACE, "PlantGro.OUT"),
            os.path.join(filex_dir, "PlantGro.OUT"),
        ]
    )
    plantgro_path = _pick_latest_by_mtime(plantgro_candidates)
    if not plantgro_path:
        plantgro_path = os.path.join(WORKSPACE, "PlantGro.OUT")

    vars_list = var_names
    if vars_list is None:
        vars_list = ["L#SD", "LAID", "LWAD", "SWAD"]
    vars_list = [str(v).strip().upper() for v in vars_list if str(v).strip()]

    obs_by_tn = _read_tmt_process_obs(tmt_path, vars_list)
    sim_by_run = _read_plantgro_vars_by_run(plantgro_path, vars_list)

    rows = []
    for e in entries:
        run_no = int(e["run"])
        tn = int(e.get("tn", -99))
        obs_pts = obs_by_tn.get(tn, [])
        sim_candidates = sim_by_run.get(run_no, {})
        sim_dates_sorted = sorted(sim_candidates.keys())

        for p in obs_pts:
            date = int(p["DATE"])
            sim_day = None
            sim_date_used = None
            if date in sim_candidates:
                sim_day = sim_candidates[date]
                sim_date_used = date
            else:
                prev_dates = [d for d in sim_dates_sorted if d <= date]
                if prev_dates:
                    sim_date_used = prev_dates[-1]
                    sim_day = sim_candidates[sim_date_used]

            row = {
                "RUN": run_no, "TN": tn, "DATE": date,
                "SIM_DATE": sim_date_used,
                "SIM_DATE_GAP_DAYS": (
                    _yyddd_day_difference(sim_date_used, date)
                    if sim_date_used is not None else np.nan
                ),
            }
            for v in vars_list:
                row[f"OBS_{v}"] = float(p.get(f"OBS_{v}", -99.0))
                if sim_day is None:
                    row[f"SIM_{v}"] = np.nan
                else:
                    row[f"SIM_{v}"] = float(sim_day.get(v, np.nan))
            rows.append(row)

    df = pd.DataFrame(rows)
    out_csv = os.path.join(run_dir or WORKSPACE, f"{prefix}_deterministic_process_compare.csv")
    df.to_csv(out_csv, index=False)
    return out_csv


def deterministic_harvest_compare(prefix, batch_file, run_dir=None):
    ensure_results_dir()
    entries = _parse_batch_entries(batch_file)
    if not entries:
        raise ValueError(f"No batch entries found in {batch_file}")

    filex0 = entries[0]["filex"]
    filex_abs = filex0 if os.path.isabs(filex0) else os.path.join(WORKSPACE, filex0)
    filex_dir = os.path.dirname(os.path.abspath(filex_abs))
    excode = _infer_excode_from_filex(filex_abs)
    tmt_path = os.path.join(filex_dir, f"{excode}.TMT") if excode else None

    freshwt_candidates = []
    if run_dir:
        freshwt_candidates.append(os.path.join(run_dir, "FreshWt.OUT"))
    freshwt_candidates.extend(
        [
            os.path.join(WORKSPACE, "FreshWt.OUT"),
            os.path.join(filex_dir, "FreshWt.OUT"),
        ]
    )
    freshwt_path = _pick_latest_by_mtime(freshwt_candidates)
    if not freshwt_path:
        freshwt_path = os.path.join(WORKSPACE, "FreshWt.OUT")

    obs_by_tn = _read_tmt_harvest_obs(tmt_path)
    sim_chpdt = _read_freshwt_var_by_run(freshwt_path, "CHPDT")
    sim_chfpw = _read_freshwt_var_by_run(freshwt_path, "CHFPW")

    rows = []
    for e in entries:
        run_no = int(e["run"])
        tn = int(e.get("tn", -99))
        obs_events = obs_by_tn.get(tn, [])
        prev_sim_dry = None
        prev_sim_fresh = None
        for ev in obs_events:
            date = int(ev["DATE"])
            sim_date = _yyddd_add_days(date, 1)
            sim_dry_cum = _nearest_on_or_before(sim_chpdt.get(run_no, {}), sim_date)
            sim_fresh_cum = _nearest_on_or_before(sim_chfpw.get(run_no, {}), sim_date)
            sim_dry_cum = float(sim_dry_cum) if sim_dry_cum is not None else np.nan
            sim_fresh_cum = float(sim_fresh_cum) if sim_fresh_cum is not None else np.nan

            if prev_sim_dry is None or np.isnan(prev_sim_dry):
                sim_dry_inc = sim_dry_cum
            elif np.isnan(sim_dry_cum):
                sim_dry_inc = np.nan
            else:
                sim_dry_inc = sim_dry_cum - prev_sim_dry

            if prev_sim_fresh is None or np.isnan(prev_sim_fresh):
                sim_fresh_inc = sim_fresh_cum
            elif np.isnan(sim_fresh_cum):
                sim_fresh_inc = np.nan
            else:
                sim_fresh_inc = sim_fresh_cum - prev_sim_fresh

            prev_sim_dry = sim_dry_cum
            prev_sim_fresh = sim_fresh_cum

            rows.append(
                {
                    "RUN": run_no,
                    "TN": tn,
                    **ev,
                    "SIM_DRY_CUM": sim_dry_cum,
                    "SIM_DRY_INC": sim_dry_inc,
                    "SIM_FRESH_CUM": sim_fresh_cum,
                    "SIM_FRESH_INC": sim_fresh_inc,
                }
            )

    df = pd.DataFrame(rows)
    out_csv = os.path.join(run_dir or WORKSPACE, f"{prefix}_deterministic_harvest_compare.csv")
    df.to_csv(out_csv, index=False)
    return out_csv


def _read_evaluate_out(path):
    rows = []
    header = None
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.rstrip("\n")
            if not s.strip():
                continue
            stripped = s.lstrip()
            if stripped.startswith("@RUN"):
                header = stripped.split()
                continue
            if header is None:
                continue
            if stripped.startswith("*") or stripped.startswith("@"):  
                continue
            if not re.match(r"^\s*\d+\s+", s):
                continue
            parts = stripped.split()
            if len(parts) < len(header):
                parts += ["-99"] * (len(header) - len(parts))
            rows.append(dict(zip(header, parts[: len(header)])))
    return pd.DataFrame(rows)


def deterministic_joint_compare(prefix, batch_file, var_bases=None, run_dir=None):
    ensure_results_dir()
    entries = _parse_batch_entries(batch_file)
    if not entries:
        raise ValueError(f"No batch entries found in {batch_file}")

    filex0 = entries[0]["filex"]
    filex_abs = filex0 if os.path.isabs(filex0) else os.path.join(WORKSPACE, filex0)
    filex_dir = os.path.dirname(os.path.abspath(filex_abs))

    evaluate_candidates = []
    if run_dir:
        evaluate_candidates.append(os.path.join(run_dir, "Evaluate.OUT"))
    evaluate_candidates.extend(
        [
            os.path.join(WORKSPACE, "Evaluate.OUT"),
            os.path.join(filex_dir, "Evaluate.OUT"),
        ]
    )
    evaluate_path = _pick_latest_by_mtime(evaluate_candidates)
    if not evaluate_path:
        evaluate_path = os.path.join(WORKSPACE, "Evaluate.OUT")
    if not os.path.exists(evaluate_path):
        raise FileNotFoundError(
            f"Evaluate.OUT not found (looked in run_dir={run_dir}, {WORKSPACE}, and {filex_dir})"
        )

    bases = var_bases
    if bases is None:
        bases = ["HWAM", "LAIX", "CNAM", "CNAA"]
    bases = [str(v).strip().upper() for v in bases if str(v).strip()]
    if not bases:
        raise ValueError("Empty var_bases")

    df = _read_evaluate_out(evaluate_path)
    if df.empty:
        raise ValueError(f"Evaluate.OUT is empty: {evaluate_path}")

    run_to_tn = {int(e["run"]): int(e.get("tn", -99)) for e in entries}
    if "@RUN" not in df.columns:
        raise ValueError("Evaluate.OUT missing @RUN column")
    df["RUN"] = pd.to_numeric(df["@RUN"], errors="coerce")
    df = df[~df["RUN"].isna()].copy()
    df["RUN"] = df["RUN"].astype(int)
    df["TN"] = df["RUN"].map(run_to_tn).fillna(-99).astype(int)

    out_rows = []
    for _, r in df.iterrows():
        row = {"RUN": int(r["RUN"]), "TN": int(r["TN"])}
        for b in bases:
            om = f"{b}M"
            os_ = f"{b}S"
            if om in df.columns:
                row[f"OBS_{b}"] = float(pd.to_numeric(r.get(om), errors="coerce"))
            else:
                row[f"OBS_{b}"] = np.nan
            if os_ in df.columns:
                row[f"SIM_{b}"] = float(pd.to_numeric(r.get(os_), errors="coerce"))
            else:
                row[f"SIM_{b}"] = np.nan
        out_rows.append(row)

    out_df = pd.DataFrame(out_rows)
    out_csv = os.path.join(run_dir or WORKSPACE, f"{prefix}_deterministic_joint_compare.csv")
    out_df.to_csv(out_csv, index=False)
    return out_csv

def ensure_results_dir():
    pass  # Deprecated, use run_dir directly

def get_ensemble_files(pattern):
    """
    Finds files matching pattern in both RESULTS_DIR and WORKSPACE.
    Returns combined list of files.
    """
    files = []
    files.extend(glob.glob(os.path.join(WORKSPACE, pattern)))
    # Removed old RESULTS_DIR lookup for simplicity
    runs_root = os.path.join(WORKSPACE, "Calibration_Results", "_runs")
    if os.path.isdir(runs_root):
        files.extend(glob.glob(os.path.join(runs_root, "*", "*", pattern)))
        files.extend(glob.glob(os.path.join(runs_root, "*", pattern)))

    return sorted({os.path.abspath(p) for p in files})


def _pick_latest_by_mtime(paths):
    if not paths:
        return None
    existing = [p for p in paths if p and os.path.exists(p)]
    if not existing:
        return None
    return max(existing, key=lambda p: os.path.getmtime(p))

def cleanup_workspace(prefix, run_dir=None):
    """Moves PEST output CSV files to run_dir."""
    dst_dir = run_dir or WORKSPACE
    if dst_dir == WORKSPACE: return
    print(f"\n[Cleanup] Moving intermediate CSV files to {dst_dir}...")
    patterns = [
        f"{prefix}.*.obs.csv",
        f"{prefix}.*.par.csv",
        f"{prefix}.phi.*.csv",
        f"{prefix}.*.pdc.csv",
        f"{prefix}.*.pcs.csv",
    ]
    count = 0
    for pat in patterns:
        files = glob.glob(os.path.join(WORKSPACE, pat))
        for src in files:
            dst = os.path.join(dst_dir, os.path.basename(src))
            try:
                shutil.move(src, dst)
                count += 1
            except Exception as e:
                print(f"Warning: Could not move {src}: {e}")
                
    print(f"Moved {count} files to {RESULTS_DIR}")

def _find_pst_path(prefix, run_dir=None):
    candidates = []
    if run_dir:
        candidates.append(os.path.join(run_dir, f"{prefix}.pst"))
    candidates.append(os.path.join(WORKSPACE, f"{prefix}.pst"))

    runs_root = os.path.join(RESULTS_DIR, "_runs")
    if os.path.isdir(runs_root):
        candidates.extend(glob.glob(os.path.join(runs_root, "*", f"{prefix}.pst")))
        candidates.extend(glob.glob(os.path.join(runs_root, "*", "*", f"{prefix}.pst")))

    return _pick_latest_by_mtime(candidates)


def _write_and_run_deterministic(prefix, batch_file, param_csv, det_dir, harvest_var="CHPDT"):
    batch_file = os.path.abspath(batch_file)
    param_csv = os.path.abspath(param_csv)
    det_dir = os.path.abspath(det_dir)
    os.makedirs(det_dir, exist_ok=True)

    batch_local = os.path.join(det_dir, "DSSBatch.v48")
    shutil.copy2(batch_file, batch_local)

    run_dssat_path = os.path.join(WORKSPACE, "run_dssat.py")
    cmd = [
        sys.executable,
        run_dssat_path,
        "--param-csv",
        param_csv,
        "--batch",
        batch_local,
        "--harvest-var",
        str(harvest_var),
    ]
    subprocess.run(cmd, cwd=det_dir, check=True)
    return batch_local


def _make_standard_plots(prefix, results_dir=None, out_dir=None, no_timeseries=False):
    results_dir = results_dir or WORKSPACE
    import plot_results as pr

    results_dir = os.path.abspath(results_dir)
    out_dir = out_dir.strip() if isinstance(out_dir, str) else ""
    out_dir = out_dir or os.path.join(results_dir, "plots", prefix)
    pr._ensure_dir(out_dir)

    process_csv = os.path.join(results_dir, f"{prefix}_deterministic_process_compare.csv")
    harvest_csv = os.path.join(results_dir, f"{prefix}_deterministic_harvest_compare.csv")
    joint_csv = os.path.join(results_dir, f"{prefix}_deterministic_joint_compare.csv")

    if os.path.exists(process_csv):
        dfp = pd.read_csv(process_csv)
        pr._scatter_1to1(dfp, "OBS_LAID", "SIM_LAID", f"{prefix}: LAID", os.path.join(out_dir, "scatter_LAID.png"))
        pr._scatter_1to1(dfp, "OBS_LWAD", "SIM_LWAD", f"{prefix}: LWAD", os.path.join(out_dir, "scatter_LWAD.png"))
        pr._scatter_1to1(dfp, "OBS_SWAD", "SIM_SWAD", f"{prefix}: SWAD", os.path.join(out_dir, "scatter_SWAD.png"))
        if not no_timeseries:
            pr._facet_timeseries(
                dfp,
                tn_col="TN",
                date_col="DATE",
                pairs=[("OBS_LAID", "SIM_LAID", "LAID")],
                title=f"{prefix}: LAID time series by TN",
                out_png=os.path.join(out_dir, "timeseries_LAID_by_TN.png"),
            )

    if os.path.exists(harvest_csv):
        dfh = pd.read_csv(harvest_csv)
        pr._scatter_1to1(
            dfh,
            "OBS_FRESH_CUM",
            "SIM_FRESH_CUM",
            f"{prefix}: Fresh yield cumulative",
            os.path.join(out_dir, "scatter_fresh_cum.png"),
        )
        pr._scatter_1to1(
            dfh,
            "OBS_DRY_CUM",
            "SIM_DRY_CUM",
            f"{prefix}: Dry yield cumulative",
            os.path.join(out_dir, "scatter_dry_cum.png"),
        )
        if not no_timeseries:
            pr._facet_timeseries(
                dfh,
                tn_col="TN",
                date_col="DATE",
                pairs=[("OBS_FRESH_CUM", "SIM_FRESH_CUM", "FreshCum")],
                title=f"{prefix}: cumulative fresh yield by TN",
                out_png=os.path.join(out_dir, "timeseries_fresh_cum_by_TN.png"),
            )
            pr._facet_timeseries(
                dfh,
                tn_col="TN",
                date_col="DATE",
                pairs=[("OBS_DRY_CUM", "SIM_DRY_CUM", "DryCum")],
                title=f"{prefix}: cumulative dry yield by TN",
                out_png=os.path.join(out_dir, "timeseries_dry_cum_by_TN.png"),
            )

    if os.path.exists(joint_csv):
        dfj = pd.read_csv(joint_csv)
        pr._scatter_1to1(dfj, "OBS_HWAM", "SIM_HWAM", f"{prefix}: HWAM", os.path.join(out_dir, "scatter_HWAM.png"))
        pr._scatter_1to1(dfj, "OBS_LAIX", "SIM_LAIX", f"{prefix}: LAIX", os.path.join(out_dir, "scatter_LAIX.png"))
        pr._scatter_1to1(dfj, "OBS_CNAM", "SIM_CNAM", f"{prefix}: CNAM", os.path.join(out_dir, "scatter_CNAM.png"))

    return out_dir


def analyze(prefix, run_dir=None, batch_file=None, make_plots=True, plots_no_timeseries=False):
    pst_file = _find_pst_path(prefix, run_dir=run_dir)
    print(f"Loading PEST control file: {pst_file}")
    if not pst_file or not os.path.exists(pst_file):
        print(f"Error: {prefix}.pst not found")
        return

    import warnings

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"Failed to import legacy module\..*",
            category=UserWarning,
        )
        import pyemu

    pst = pyemu.Pst(pst_file)

    batch_file = (batch_file or "").strip() or os.path.join(WORKSPACE, "DSSBatch.v48")
    
    # Ensure results directory exists
    ensure_results_dir()
    
    # Get measured values and weights
    obs = pst.observation_data.copy()
    obs['measured'] = obs['obsval']
    
    # Find the latest observation ensemble file
    obs_files = get_ensemble_files(f"{prefix}.*.obs.csv")
    
    # Filter for numeric iteration numbers
    iter_files = []
    for f in obs_files:
        basename = os.path.basename(f)
        parts = basename.split('.')
        if len(parts) >= 4 and parts[1].isdigit():
            try:
                mtime = os.path.getmtime(f)
            except Exception:
                mtime = -1
            iter_files.append((int(parts[1]), mtime, f))
            
    if not iter_files:
        print("No observation ensemble files found!")
        return

    # Sort by iteration
    iter_files.sort(key=lambda x: (x[0], x[1]))
    latest_iter, _, latest_file = iter_files[-1]
    print(f"Analyzing results from iteration {latest_iter} ({latest_file})...")
    
    # Read ensemble
    ens = pd.read_csv(latest_file, index_col=0)
    
    # Calculate statistics across the ensemble
    # Mean simulation
    sim_mean = ens.mean(axis=0)
    # Standard deviation (uncertainty)
    sim_std = ens.std(axis=0)
    # 95% Confidence Interval
    sim_lower = ens.quantile(0.025, axis=0)
    sim_upper = ens.quantile(0.975, axis=0)
    
    # Create results dataframe
    results = []
    for obs_name in obs.index:
        if obs_name in sim_mean.index:
            measured = obs.loc[obs_name, 'measured']
            weight = obs.loc[obs_name, 'weight']
            group = obs.loc[obs_name, 'obgnme']
            
            simulated = sim_mean[obs_name]
            residual = measured - simulated
            
            # Avoid division by zero for percent error
            pct_error = (residual / measured * 100) if measured != 0 else 0
            if measured == -99 or weight == 0:
                 pct_error = np.nan # Ignore missing data or zero-weight
            
            results.append({
                "Observation": obs_name,
                "Group": group,
                "Measured": measured,
                "Simulated_Mean": simulated,
                "Residual": residual,
                "Percent_Error": pct_error,
                "Weight": weight,
                "Sim_Lower_95": sim_lower[obs_name],
                "Sim_Upper_95": sim_upper[obs_name],
                "Sim_Std_Dev": sim_std[obs_name]
            })
            
    res_df = pd.DataFrame(results)
    
    # Save to RESULTS_DIR
    output_path = os.path.join(RESULTS_DIR, f"{prefix}_error_diag.csv")
    res_df.to_csv(output_path, index=False)
    print(f"Detailed analysis saved to {output_path}")
    
    # Print summary statistics
    valid_obs = res_df[res_df['Weight'] > 0]
    if not valid_obs.empty:
        rmse = np.sqrt((valid_obs['Residual']**2).mean())
        bias = valid_obs['Residual'].mean()
        print("\nSummary Statistics (Weighted Observations Only):")
        print(f"  RMSE: {rmse:.4f}")
        print(f"  Mean Bias: {bias:.4f}")
    else:
        print("\nNo weighted observations found for statistics.")

    # Parameter Analysis
    par_files = get_ensemble_files(f"{prefix}.*.par.csv")
    par_iter_files = []
    for f in par_files:
        basename = os.path.basename(f)
        parts = basename.split('.')
        if len(parts) >= 4 and parts[1].isdigit():
            try:
                mtime = os.path.getmtime(f)
            except Exception:
                mtime = -1
            par_iter_files.append((int(parts[1]), mtime, f))
    
    if par_iter_files:
        par_iter_files.sort(key=lambda x: (x[0], x[1]))
        latest_par_iter, _, latest_par_file = par_iter_files[-1]
        print(f"\nAnalyzing parameters from iteration {latest_par_iter}...")
        
        par_ens = pd.read_csv(latest_par_file, index_col=0)
        
        # 1. Uncertainty Statistics
        par_stats = par_ens.describe(percentiles=[0.025, 0.975]).T
        par_stats['mean'] = par_ens.mean()
        
        par_output_path = os.path.join(RESULTS_DIR, f"{prefix}_parameter_uncertainty.csv")
        par_stats.to_csv(par_output_path)
        print(f"Parameter uncertainty saved to {par_output_path}")

        # 2. Identify Best Realization (Minimum Phi)
        phi_candidates = get_ensemble_files(f"{prefix}.phi.actual.csv")
        phi_file = _pick_latest_by_mtime(phi_candidates)
        if not phi_file:
            phi_file = os.path.join(RESULTS_DIR, f"{prefix}.phi.actual.csv")
            if not os.path.exists(phi_file):
                phi_file = os.path.join(WORKSPACE, f"{prefix}.phi.actual.csv")
            
        if os.path.exists(phi_file):
             phi_df = pd.read_csv(phi_file)
             # Get last iteration rows
             last_iter_phi = phi_df[phi_df['iteration'] == latest_par_iter]
             if not last_iter_phi.empty:
                 # Phi file columns are: iteration, total_runs, mean, std, min, max, <realization_names>...
                 # Drop metadata columns to find min realization
                 meta_cols = ['iteration', 'total_runs', 'mean', 'standard_deviation', 'min', 'max']
                 real_cols = [c for c in last_iter_phi.columns if c not in meta_cols]
                 
                 # Get the row values for realizations
                 phi_vals = last_iter_phi[real_cols].iloc[0]
                 best_real_name = phi_vals.idxmin()
                 best_phi_val = phi_vals.min()
                 
                 print("\n[Best Fit Analysis]")
                 print(f"Best Realization: {best_real_name} (Phi = {best_phi_val:.4f})")
                 
                 # Extract best parameters
                 if best_real_name in par_ens.index:
                     best_pars = par_ens.loc[best_real_name]
                     best_par_file = os.path.join(RESULTS_DIR, f"{prefix}_best_parameters.csv")
                     best_pars.to_csv(best_par_file, header=["Value"])
                     print(f"Best parameter set saved to {best_par_file}")
                     print("(Recommended for use in deterministic simulations)")

                     fixed_csv = os.path.join(RESULTS_DIR, f"{prefix}_best_parameters_fixed.csv")
                     pd.DataFrame({"name": best_pars.index, "value": best_pars.values}).to_csv(
                         fixed_csv, index=False, encoding="utf-8-sig"
                     )
                     print(f"Fixed-parameter CSV saved to {fixed_csv}")

                     if make_plots:
                         try:
                             det_dir = os.path.join(RESULTS_DIR, "_det", prefix)
                             batch_local = _write_and_run_deterministic(prefix, batch_file, fixed_csv, det_dir)
                             deterministic_harvest_compare(prefix, batch_local, run_dir=det_dir)
                             deterministic_process_compare(prefix, batch_local, run_dir=det_dir)
                             deterministic_joint_compare(prefix, batch_local, run_dir=det_dir)
                             out_dir = _make_standard_plots(prefix, results_dir=RESULTS_DIR, out_dir=None, no_timeseries=bool(plots_no_timeseries))
                             print(f"Plots saved to {out_dir}")
                         except Exception as e:
                             print(f"Warning: failed to generate plots: {e}")

                     try:
                         par_data = pst.parameter_data.copy()
                         par_data.index = par_data.index.astype(str)
                         rows = []
                         tol_rel = 1e-6
                         tol_abs = 1e-10
                         for name in best_pars.index.astype(str):
                             if name not in par_data.index:
                                 continue
                             v = float(best_pars.loc[name])
                             lb = float(par_data.loc[name, "parlbnd"])
                             ub = float(par_data.loc[name, "parubnd"])
                             if lb > ub:
                                 lb, ub = ub, lb
                             rng = ub - lb
                             tol = max(tol_abs, tol_rel * abs(rng))
                             near_lb = abs(v - lb) <= tol
                             near_ub = abs(v - ub) <= tol
                             rel_pos = (v - lb) / rng if rng > 0 else np.nan
                             frac_lb = np.nan
                             frac_ub = np.nan
                             if name in par_ens.columns:
                                 s = pd.to_numeric(par_ens[name], errors="coerce")
                                 frac_lb = float(np.mean(np.abs(s - lb) <= tol))
                                 frac_ub = float(np.mean(np.abs(s - ub) <= tol))
                             rows.append(
                                 {
                                     "name": name,
                                     "value": v,
                                     "lower": lb,
                                     "upper": ub,
                                     "near_lower": bool(near_lb),
                                     "near_upper": bool(near_ub),
                                     "rel_pos": rel_pos,
                                     "ens_frac_near_lower": frac_lb,
                                     "ens_frac_near_upper": frac_ub,
                                 }
                             )

                         if rows:
                             bdf = pd.DataFrame(rows)
                             bdf = bdf.sort_values(by=["near_lower", "near_upper", "ens_frac_near_lower", "ens_frac_near_upper"], ascending=False)
                             bound_file = os.path.join(RESULTS_DIR, f"{prefix}_bound_hits.csv")
                             bdf.to_csv(bound_file, index=False, encoding="utf-8-sig")
                             n_near = int((bdf["near_lower"] | bdf["near_upper"]).sum())
                             if n_near > 0:
                                 print(f"\n[Bound Hit Report] {n_near} best-fit parameters are at bounds")
                                 print(f"Report saved to {bound_file}")
                             else:
                                 print("\n[Bound Hit Report] No best-fit parameters at bounds")
                                 print(f"Report saved to {bound_file}")
                     except Exception as e:
                         print(f"Warning: could not generate bound-hit report: {e}")
                 else:
                     print(f"Warning: Realization {best_real_name} not found in parameter ensemble.")

    # Perform Cleanup
    cleanup_workspace(prefix, run_dir=run_dir)


def _safe_series(df, col):
    if col not in df.columns:
        return pd.Series(dtype=float)
    s = pd.to_numeric(df[col], errors="coerce")
    s = s.replace([-99, -99.0], np.nan)
    return s


def _rmse_nrmse_d(obs, sim):
    obs = pd.to_numeric(obs, errors="coerce").astype(float)
    sim = pd.to_numeric(sim, errors="coerce").astype(float)
    obs = obs.replace([-99, -99.0], np.nan)
    sim = sim.replace([-99, -99.0], np.nan)
    mask = (~obs.isna()) & (~sim.isna())
    n = int(mask.sum())
    if n == 0:
        return 0, np.nan, np.nan, np.nan

    o = obs[mask].astype(float)
    s = sim[mask].astype(float)
    diff = (s - o).astype(float)
    rmse = float(np.sqrt(np.mean(diff * diff)))

    mean_obs = float(np.mean(o))
    if mean_obs == 0.0:
        nrmse = np.nan
    else:
        nrmse = float(rmse / abs(mean_obs) * 100.0)

    denom = np.sum((np.abs(s - mean_obs) + np.abs(o - mean_obs)) ** 2)
    if denom == 0.0:
        d_index = np.nan
    else:
        d_index = float(1.0 - (np.sum((s - o) ** 2) / denom))
    return n, rmse, nrmse, d_index


def _metrics_rows_from_pairs(df, tn_col, pairs, prefix, source, scope_label):
    rows = []
    for var, obs_col, sim_col, target_nrmse, target_d in pairs:
        n, rmse, nrmse, d_index = _rmse_nrmse_d(df.get(obs_col), df.get(sim_col))
        rows.append(
            {
                "prefix": prefix,
                "scope": scope_label,
                "TN": int(df[tn_col].iloc[0]) if scope_label != "overall" and tn_col in df.columns else -99,
                "source": source,
                "variable": var,
                "n": n,
                "rmse": rmse,
                "nrmse_pct": nrmse,
                "d_index": d_index,
                "target_nrmse_pct": target_nrmse,
                "target_d_index": target_d,
            }
        )
    return rows


def _harvest_total_by_run(df):
    if df.empty:
        return pd.DataFrame(columns=["RUN", "TN", "OBS_DRY_TOTAL", "SIM_DRY_TOTAL"])

    dd = df.copy()
    if "DATE" not in dd.columns:
        dd["DATE"] = 0
    dd["DATE"] = pd.to_numeric(dd["DATE"], errors="coerce")
    dd = dd.sort_values(by=["RUN", "DATE"])
    out = dd.groupby(["RUN", "TN"], as_index=False).tail(1)
    out = out[["RUN", "TN", "OBS_DRY_CUM", "SIM_DRY_CUM"]].rename(
        columns={"OBS_DRY_CUM": "OBS_DRY_TOTAL", "SIM_DRY_CUM": "SIM_DRY_TOTAL"}
    )
    return out


def metrics_grid(prefixes, batch_file, out_name=None, joint_vars=None, process_vars=None, run_dir=None):
    ensure_results_dir()
    prefixes = [p.strip() for p in (prefixes or []) if p and p.strip()]
    if not prefixes:
        raise ValueError("No valid prefixes provided")

    joint_bases = joint_vars
    if joint_bases is None:
        joint_bases = ["HWAM", "LAIX", "CNAM", "CNAA"]
    joint_bases = [str(v).strip().upper() for v in joint_bases if str(v).strip()]

    proc_vars = process_vars
    if proc_vars is None:
        proc_vars = ["LAID", "LWAD", "SWAD"]
    proc_vars = [str(v).strip().upper() for v in proc_vars if str(v).strip()]

    all_rows = []
    for prefix in prefixes:
        harvest_csv = os.path.join(RESULTS_DIR, f"{prefix}_deterministic_harvest_compare.csv")
        if not os.path.exists(harvest_csv):
            harvest_csv = deterministic_harvest_compare(prefix, batch_file, run_dir=run_dir)
        try:
            harvest_df = pd.read_csv(harvest_csv)
        except Exception:
            harvest_csv = deterministic_harvest_compare(prefix, batch_file, run_dir=run_dir)
            harvest_df = pd.read_csv(harvest_csv)
        if harvest_df.empty:
            harvest_csv = deterministic_harvest_compare(prefix, batch_file, run_dir=run_dir)
            harvest_df = pd.read_csv(harvest_csv)

        process_csv = os.path.join(RESULTS_DIR, f"{prefix}_deterministic_process_compare.csv")
        if not os.path.exists(process_csv):
            process_csv = deterministic_process_compare(prefix, batch_file, var_names=proc_vars, run_dir=run_dir)
        try:
            process_df = pd.read_csv(process_csv)
        except Exception:
            process_csv = deterministic_process_compare(prefix, batch_file, var_names=proc_vars, run_dir=run_dir)
            process_df = pd.read_csv(process_csv)
        if process_df.empty:
            process_csv = deterministic_process_compare(prefix, batch_file, var_names=proc_vars, run_dir=run_dir)
            process_df = pd.read_csv(process_csv)

        joint_csv = os.path.join(RESULTS_DIR, f"{prefix}_deterministic_joint_compare.csv")
        if not os.path.exists(joint_csv):
            joint_csv = deterministic_joint_compare(prefix, batch_file, var_bases=joint_bases, run_dir=run_dir)
        try:
            joint_df = pd.read_csv(joint_csv)
        except Exception:
            joint_csv = deterministic_joint_compare(prefix, batch_file, var_bases=joint_bases, run_dir=run_dir)
            joint_df = pd.read_csv(joint_csv)
        if joint_df.empty:
            joint_csv = deterministic_joint_compare(prefix, batch_file, var_bases=joint_bases, run_dir=run_dir)
            joint_df = pd.read_csv(joint_csv)

        harvest_df_total = _harvest_total_by_run(harvest_df)

        harvest_pairs = [
            ("dry_cum", "OBS_DRY_CUM", "SIM_DRY_CUM", 15.0, 0.85),
            ("dry_inc", "OBS_DRY_INC", "SIM_DRY_INC", np.nan, np.nan),
            ("dry_total", "OBS_DRY_TOTAL", "SIM_DRY_TOTAL", 15.0, 0.85),
        ]

        process_pairs = [
            (v, f"OBS_{v}", f"SIM_{v}", 20.0 if v == "LAID" else np.nan, 0.80 if v == "LAID" else np.nan)
            for v in proc_vars
        ]

        joint_pairs = [
            (b, f"OBS_{b}", f"SIM_{b}", 15.0 if b == "HWAM" else 20.0 if b == "LAIX" else np.nan, 0.85 if b == "HWAM" else 0.80 if b == "LAIX" else np.nan)
            for b in joint_bases
        ]

        all_rows.extend(_metrics_rows_from_pairs(harvest_df, "TN", harvest_pairs[:2], prefix, "harvest_curve", "overall"))
        all_rows.extend(
            _metrics_rows_from_pairs(harvest_df_total, "TN", harvest_pairs[2:], prefix, "harvest_total", "overall")
        )
        all_rows.extend(_metrics_rows_from_pairs(process_df, "TN", process_pairs, prefix, "process", "overall"))
        all_rows.extend(_metrics_rows_from_pairs(joint_df, "TN", joint_pairs, prefix, "joint", "overall"))

        for tn, g in harvest_df.groupby("TN"):
            all_rows.extend(_metrics_rows_from_pairs(g, "TN", harvest_pairs[:2], prefix, "harvest_curve", f"TN{int(tn)}"))
        for tn, g in harvest_df_total.groupby("TN"):
            all_rows.extend(
                _metrics_rows_from_pairs(g, "TN", harvest_pairs[2:], prefix, "harvest_total", f"TN{int(tn)}")
            )
        for tn, g in process_df.groupby("TN"):
            all_rows.extend(_metrics_rows_from_pairs(g, "TN", process_pairs, prefix, "process", f"TN{int(tn)}"))
        for tn, g in joint_df.groupby("TN"):
            all_rows.extend(_metrics_rows_from_pairs(g, "TN", joint_pairs, prefix, "joint", f"TN{int(tn)}"))

    out_df = pd.DataFrame(all_rows)
    out_file = out_name.strip() if out_name else "metrics_grid.csv"
    if not out_file.lower().endswith(".csv"):
        out_file += ".csv"
    out_path = os.path.join(RESULTS_DIR, out_file)
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    return out_path


def _harvest_metrics_from_compare_df(df):
    metrics = {}
    pairs = [
        ("OBS_DRY_CUM", "SIM_DRY_CUM", "dry_cum"),
        ("OBS_DRY_INC", "SIM_DRY_INC", "dry_inc"),
        ("OBS_FRESH_CUM", "SIM_FRESH_CUM", "fresh_cum"),
        ("OBS_FRESH_INC", "SIM_FRESH_INC", "fresh_inc"),
    ]
    for obs_col, sim_col, tag in pairs:
        obs = _safe_series(df, obs_col)
        sim = _safe_series(df, sim_col)
        if obs.empty or sim.empty:
            metrics[f"n_{tag}"] = 0
            metrics[f"rmse_{tag}"] = np.nan
            metrics[f"mape_{tag}"] = np.nan
            continue

        mask = (~obs.isna()) & (~sim.isna())
        n = int(mask.sum())
        metrics[f"n_{tag}"] = n
        if n == 0:
            metrics[f"rmse_{tag}"] = np.nan
            metrics[f"mape_{tag}"] = np.nan
            continue

        d = (sim[mask] - obs[mask]).astype(float)
        metrics[f"rmse_{tag}"] = float(np.sqrt(np.mean(d * d)))

        denom = obs[mask].astype(float)
        mask2 = denom != 0
        if int(mask2.sum()) == 0:
            metrics[f"mape_{tag}"] = np.nan
        else:
            metrics[f"mape_{tag}"] = float(np.mean(np.abs(d[mask2] / denom[mask2])) * 100.0)

    return metrics


def _process_metrics_from_compare_df(df, var_names=None):
    vars_list = var_names
    if vars_list is None:
        vars_list = ["L#SD", "LAID", "LWAD", "SWAD"]
    vars_list = [str(v).strip().upper() for v in vars_list if str(v).strip()]

    metrics = {}
    for v in vars_list:
        obs_col = f"OBS_{v}"
        sim_col = f"SIM_{v}"
        obs = _safe_series(df, obs_col)
        sim = _safe_series(df, sim_col)
        if obs.empty or sim.empty:
            metrics[f"n_{v}"] = 0
            metrics[f"rmse_{v}"] = np.nan
            metrics[f"mape_{v}"] = np.nan
            continue

        mask = (~obs.isna()) & (~sim.isna())
        n = int(mask.sum())
        metrics[f"n_{v}"] = n
        if n == 0:
            metrics[f"rmse_{v}"] = np.nan
            metrics[f"mape_{v}"] = np.nan
            continue

        d = (sim[mask] - obs[mask]).astype(float)
        metrics[f"rmse_{v}"] = float(np.sqrt(np.mean(d * d)))

        denom = obs[mask].astype(float)
        mask2 = denom != 0
        if int(mask2.sum()) == 0:
            metrics[f"mape_{v}"] = np.nan
        else:
            metrics[f"mape_{v}"] = float(np.mean(np.abs(d[mask2] / denom[mask2])) * 100.0)

    return metrics


def process_metrics(prefixes, batch_file, out_name=None, var_names=None):
    ensure_results_dir()
    rows = []
    for prefix in prefixes:
        prefix = (prefix or "").strip()
        if not prefix:
            continue
        compare_csv = os.path.join(RESULTS_DIR, f"{prefix}_deterministic_process_compare.csv")
        if not os.path.exists(compare_csv):
            compare_csv = os.path.join(WORKSPACE, "Calibration_Results", f"{prefix}_deterministic_process_compare.csv")
        if not os.path.exists(compare_csv):
            compare_csv = os.path.join(WORKSPACE, f"{prefix}_deterministic_process_compare.csv")
        if not os.path.exists(compare_csv):
            compare_csv = deterministic_process_compare(prefix, batch_file, var_names=var_names)

        df = pd.read_csv(compare_csv)
        m = _process_metrics_from_compare_df(df, var_names=var_names)
        m["prefix"] = prefix
        m["compare_csv"] = os.path.basename(compare_csv)
        rows.append(m)

    out_df = pd.DataFrame(rows)
    if out_df.empty:
        raise ValueError("No valid prefixes provided")
    out_df = out_df.set_index("prefix").sort_index()

    out_file = out_name.strip() if out_name else "process_metrics.csv"
    if not out_file.lower().endswith(".csv"):
        out_file += ".csv"
    out_path = os.path.join(RESULTS_DIR, out_file)
    out_df.to_csv(out_path)
    return out_path


def harvest_metrics(prefixes, batch_file, out_name=None):
    ensure_results_dir()
    rows = []
    for prefix in prefixes:
        prefix = (prefix or "").strip()
        if not prefix:
            continue
        compare_csv = os.path.join(RESULTS_DIR, f"{prefix}_deterministic_harvest_compare.csv")
        if not os.path.exists(compare_csv):
            compare_csv = os.path.join(WORKSPACE, "Calibration_Results", f"{prefix}_deterministic_harvest_compare.csv")
        if not os.path.exists(compare_csv):
            compare_csv = os.path.join(WORKSPACE, f"{prefix}_deterministic_harvest_compare.csv")
        if not os.path.exists(compare_csv):
            compare_csv = deterministic_harvest_compare(prefix, batch_file)

        df = pd.read_csv(compare_csv)
        m = _harvest_metrics_from_compare_df(df)
        m["prefix"] = prefix
        m["compare_csv"] = os.path.basename(compare_csv)
        rows.append(m)

    out_df = pd.DataFrame(rows)
    if out_df.empty:
        raise ValueError("No valid prefixes provided")
    out_df = out_df.set_index("prefix").sort_index()

    out_file = out_name.strip() if out_name else "harvest_metrics.csv"
    if not out_file.lower().endswith(".csv"):
        out_file += ".csv"
    out_path = os.path.join(RESULTS_DIR, out_file)
    out_df.to_csv(out_path)
    return out_path


def suggest_xxql2501_bounds(prefix, bounds_review_csv, out_path=None, extend_frac=0.20):
    ensure_results_dir()
    bh_path = os.path.join(RESULTS_DIR, f"{prefix}_bound_hits.csv")
    if not os.path.exists(bh_path):
        raise FileNotFoundError(f"Bound hit report not found: {bh_path}")
    bdf = pd.read_csv(bh_path)
    if bdf.empty:
        raise ValueError(f"Empty bound hit report: {bh_path}")

    base_csv = bounds_review_csv
    if not base_csv:
        raise ValueError("bounds_review_csv is required")
    if not os.path.exists(base_csv):
        raise FileNotFoundError(f"Bounds review CSV not found: {base_csv}")
    sdf = pd.read_csv(base_csv)
    if sdf.empty:
        raise ValueError(f"Empty bounds review CSV: {base_csv}")

    cols = {str(c).strip().lower(): c for c in sdf.columns}
    name_c = cols.get("name") or cols.get("parnme") or cols.get("parameter")
    lb_c = cols.get("lower") or cols.get("lb") or cols.get("parlbnd")
    ub_c = cols.get("upper") or cols.get("ub") or cols.get("parubnd")
    if not name_c or not lb_c or not ub_c:
        raise ValueError("Bounds review CSV must contain name/lower/upper columns")

    if "near_lower" not in bdf.columns or "near_upper" not in bdf.columns:
        raise ValueError("Bound hit report missing near_lower/near_upper columns")
    hit = bdf[bdf["near_lower"].astype(bool) | bdf["near_upper"].astype(bool)].copy()
    if hit.empty:
        raise ValueError("No bound hits found; no need to generate XXQL2501-specific bounds")

    hit_names = {str(x).strip().upper() for x in hit["name"].astype(str).tolist() if str(x).strip()}
    sdf["_NAME_UPPER"] = sdf[name_c].astype(str).str.strip().str.upper()
    sdf["_lb"] = pd.to_numeric(sdf[lb_c], errors="coerce")
    sdf["_ub"] = pd.to_numeric(sdf[ub_c], errors="coerce")

    extend_frac = abs(float(extend_frac))
    rows = []
    for _, r in sdf[sdf["_NAME_UPPER"].isin(hit_names)].iterrows():
        name = str(r["_NAME_UPPER"]).strip().upper()
        lb0 = float(r["_lb"]) if not pd.isna(r["_lb"]) else np.nan
        ub0 = float(r["_ub"]) if not pd.isna(r["_ub"]) else np.nan
        if np.isnan(lb0) or np.isnan(ub0):
            continue
        if lb0 > ub0:
            lb0, ub0 = ub0, lb0
        rng = ub0 - lb0
        dd = rng * extend_frac
        if dd == 0.0:
            continue

        sub = hit[hit["name"].astype(str).str.strip().str.upper() == name]
        near_lb = bool(sub["near_lower"].any()) if "near_lower" in sub.columns else False
        near_ub = bool(sub["near_upper"].any()) if "near_upper" in sub.columns else False
        frac_lb = float(sub["ens_frac_near_lower"].max()) if "ens_frac_near_lower" in sub.columns else np.nan
        frac_ub = float(sub["ens_frac_near_upper"].max()) if "ens_frac_near_upper" in sub.columns else np.nan

        lb1 = lb0 - dd if near_lb else lb0
        ub1 = ub0 + dd if near_ub else ub0

        reason = []
        if near_lb:
            reason.append(f"best_fit_at_lower_bound (ens_frac={frac_lb:.3g})" if not np.isnan(frac_lb) else "best_fit_at_lower_bound")
        if near_ub:
            reason.append(f"best_fit_at_upper_bound (ens_frac={frac_ub:.3g})" if not np.isnan(frac_ub) else "best_fit_at_upper_bound")

        rows.append(
            {
                "name": name,
                "lower": lb1,
                "upper": ub1,
                "prev_lower": lb0,
                "prev_upper": ub0,
                "extend_frac": extend_frac,
                "reason": "; ".join(reason) if reason else "",
                "evidence_file": os.path.basename(bh_path),
                "note": "XXQL2501-specific bounds suggestion; review before use",
            }
        )

    out_df = pd.DataFrame(rows)
    if out_df.empty:
        raise ValueError("No matching parameters found in bounds review CSV for the bound-hit names")

    if out_path:
        dst = out_path
    else:
        dst = os.path.join(RESULTS_DIR, f"{prefix}_xxql2501_bounds_suggestions.csv")
    out_df.to_csv(dst, index=False, encoding="utf-8-sig")
    return dst

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", default="tomato_cal")
    parser.add_argument("--run-dir", default="")
    parser.add_argument("--deterministic-harvest-compare", action="store_true")
    parser.add_argument("--deterministic-process-compare", action="store_true")
    parser.add_argument("--deterministic-joint-compare", action="store_true")
    parser.add_argument("--harvest-metrics", action="store_true")
    parser.add_argument("--process-metrics", action="store_true")
    parser.add_argument("--metrics-grid", action="store_true")
    parser.add_argument("--suggest-xxql-bounds", action="store_true")
    parser.add_argument("--prefixes", default="")
    parser.add_argument("--out", default="")
    parser.add_argument("--bounds-review-csv", default="")
    parser.add_argument("--extend-frac", type=float, default=0.20)
    parser.add_argument("--joint-vars", default="")
    parser.add_argument("--process-vars", default="")
    parser.add_argument("--batch", default=os.path.join(WORKSPACE, "DSSBatch.v48"))
    parser.add_argument("--no-plots", action="store_true")
    parser.add_argument("--plots-no-timeseries", action="store_true")
    args = parser.parse_args()

    run_dir = (args.run_dir or "").strip() or None

    prefix = (args.prefix or "tomato_cal").strip()
    if args.harvest_metrics:
        prefixes = [p.strip() for p in (args.prefixes or "").split(",") if p.strip()]
        if not prefixes:
            prefixes = [prefix]
        out_path = harvest_metrics(prefixes, args.batch, out_name=args.out)
        print(f"Harvest metrics saved to {out_path}")
    elif args.process_metrics:
        prefixes = [p.strip() for p in (args.prefixes or "").split(",") if p.strip()]
        if not prefixes:
            prefixes = [prefix]
        out_path = process_metrics(prefixes, args.batch, out_name=args.out)
        print(f"Process metrics saved to {out_path}")
    elif args.deterministic_harvest_compare:
        out_csv = deterministic_harvest_compare(prefix, args.batch, run_dir=run_dir)
        print(f"Deterministic harvest comparison saved to {out_csv}")
    elif args.deterministic_process_compare:
        out_csv = deterministic_process_compare(prefix, args.batch, run_dir=run_dir)
        print(f"Deterministic process comparison saved to {out_csv}")
    elif args.deterministic_joint_compare:
        bases = [p.strip() for p in (args.joint_vars or "").split(",") if p.strip()]
        out_csv = deterministic_joint_compare(prefix, args.batch, var_bases=bases or None, run_dir=run_dir)
        print(f"Deterministic joint comparison saved to {out_csv}")
    elif args.metrics_grid:
        prefixes = [p.strip() for p in (args.prefixes or "").split(",") if p.strip()]
        if not prefixes:
            prefixes = [prefix]
        joint_bases = [p.strip() for p in (args.joint_vars or "").split(",") if p.strip()]
        process_vars = [p.strip() for p in (args.process_vars or "").split(",") if p.strip()]
        out_path = metrics_grid(
            prefixes,
            args.batch,
            out_name=args.out,
            joint_vars=joint_bases or None,
            process_vars=process_vars or None,
            run_dir=run_dir,
        )
        print(f"Metrics grid saved to {out_path}")
    elif args.suggest_xxql_bounds:
        dst = suggest_xxql2501_bounds(
            prefix,
            bounds_review_csv=args.bounds_review_csv,
            out_path=args.out or None,
            extend_frac=float(args.extend_frac),
        )
        print(f"XXQL2501 bounds suggestions saved to {dst}")
    else:
        analyze(
            prefix,
            run_dir=run_dir,
            batch_file=args.batch,
            make_plots=not bool(args.no_plots),
            plots_no_timeseries=bool(args.plots_no_timeseries),
        )
