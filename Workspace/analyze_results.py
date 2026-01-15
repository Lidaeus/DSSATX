import argparse
import pandas as pd
import numpy as np
import os
import glob
import shutil
import re
import datetime

WORKSPACE = r"C:\DSSAT48\Tomato_Cal\Workspace"
RESULTS_DIR = os.path.join(WORKSPACE, "Calibration_Results")


def _parse_batch_entries(batch_file):
    entries = []
    if not batch_file or not os.path.exists(batch_file):
        return entries

    with open(batch_file, "r") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            if s.startswith("$") or s.startswith("@"): 
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

            if not s.strip() or s.startswith("*") or s.startswith("!"):
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
    with open(tmt_path, "r") as f:
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
                obs_dry_inc = float(e["HPODW"]) if e["HPODW"] != -99.0 else -99.0
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
                obs_fresh_inc = float(e["HFPOW"]) if e["HFPOW"] != -99.0 else -99.0
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
    with open(tmt_path, "r") as f:
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

            if not s.strip() or s.startswith("*") or s.startswith("!"):
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


def deterministic_process_compare(prefix, batch_file, var_names=None):
    ensure_results_dir()
    entries = _parse_batch_entries(batch_file)
    if not entries:
        raise ValueError(f"No batch entries found in {batch_file}")

    filex0 = entries[0]["filex"]
    filex_abs = filex0 if os.path.isabs(filex0) else os.path.join(WORKSPACE, filex0)
    filex_dir = os.path.dirname(os.path.abspath(filex_abs))
    excode = _infer_excode_from_filex(filex_abs)
    tmt_path = os.path.join(filex_dir, f"{excode}.TMT") if excode else None

    plantgro_candidates = [
        os.path.join(WORKSPACE, "PlantGro.OUT"),
        os.path.join(filex_dir, "PlantGro.OUT"),
    ]
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
            if date in sim_candidates:
                sim_day = sim_candidates[date]
            else:
                prev_dates = [d for d in sim_dates_sorted if d <= date]
                if prev_dates:
                    sim_day = sim_candidates[prev_dates[-1]]

            row = {"RUN": run_no, "TN": tn, "DATE": date}
            for v in vars_list:
                row[f"OBS_{v}"] = float(p.get(f"OBS_{v}", -99.0))
                if sim_day is None:
                    row[f"SIM_{v}"] = np.nan
                else:
                    row[f"SIM_{v}"] = float(sim_day.get(v, np.nan))
            rows.append(row)

    df = pd.DataFrame(rows)
    out_csv = os.path.join(RESULTS_DIR, f"{prefix}_deterministic_process_compare.csv")
    df.to_csv(out_csv, index=False)
    return out_csv


def deterministic_harvest_compare(prefix, batch_file):
    ensure_results_dir()
    entries = _parse_batch_entries(batch_file)
    if not entries:
        raise ValueError(f"No batch entries found in {batch_file}")

    filex0 = entries[0]["filex"]
    filex_abs = filex0 if os.path.isabs(filex0) else os.path.join(WORKSPACE, filex0)
    filex_dir = os.path.dirname(os.path.abspath(filex_abs))
    excode = _infer_excode_from_filex(filex_abs)
    tmt_path = os.path.join(filex_dir, f"{excode}.TMT") if excode else None

    freshwt_candidates = [
        os.path.join(WORKSPACE, "FreshWt.OUT"),
        os.path.join(filex_dir, "FreshWt.OUT"),
    ]
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
    out_csv = os.path.join(RESULTS_DIR, f"{prefix}_deterministic_harvest_compare.csv")
    df.to_csv(out_csv, index=False)
    return out_csv

def ensure_results_dir():
    if not os.path.exists(RESULTS_DIR):
        os.makedirs(RESULTS_DIR)
        print(f"Created results directory: {RESULTS_DIR}")

def get_ensemble_files(pattern):
    """
    Finds files matching pattern in both RESULTS_DIR and WORKSPACE.
    Returns combined list of files.
    """
    files = []
    files.extend(glob.glob(os.path.join(RESULTS_DIR, pattern)))
    files.extend(glob.glob(os.path.join(WORKSPACE, pattern)))

    runs_root = os.path.join(RESULTS_DIR, "_runs")
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

def cleanup_workspace(prefix):
    """
    Moves PEST output CSV files to RESULTS_DIR to clean up the workspace.
    """
    print("\n[Cleanup] Moving intermediate CSV files to Calibration_Results...")
    ensure_results_dir()
    
    # Patterns to move
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
            dst = os.path.join(RESULTS_DIR, os.path.basename(src))
            try:
                shutil.move(src, dst)
                count += 1
            except Exception as e:
                print(f"Warning: Could not move {src}: {e}")
                
    print(f"Moved {count} files to {RESULTS_DIR}")

def analyze(prefix):
    pst_file = os.path.join(WORKSPACE, f"{prefix}.pst")
    print(f"Loading PEST control file: {pst_file}")
    if not os.path.exists(pst_file):
        print(f"Error: {pst_file} not found!")
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
                 
                 print(f"\n[Best Fit Analysis]")
                 print(f"Best Realization: {best_real_name} (Phi = {best_phi_val:.4f})")
                 
                 # Extract best parameters
                 if best_real_name in par_ens.index:
                     best_pars = par_ens.loc[best_real_name]
                     best_par_file = os.path.join(RESULTS_DIR, f"{prefix}_best_parameters.csv")
                     best_pars.to_csv(best_par_file, header=["Value"])
                     print(f"Best parameter set saved to {best_par_file}")
                     print("(Recommended for use in deterministic simulations)")
                 else:
                     print(f"Warning: Realization {best_real_name} not found in parameter ensemble.")

    # Perform Cleanup
    cleanup_workspace(prefix)


def _safe_series(df, col):
    if col not in df.columns:
        return pd.Series(dtype=float)
    s = pd.to_numeric(df[col], errors="coerce")
    s = s.replace([-99, -99.0], np.nan)
    return s


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

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", default="tomato_cal")
    parser.add_argument("--deterministic-harvest-compare", action="store_true")
    parser.add_argument("--deterministic-process-compare", action="store_true")
    parser.add_argument("--harvest-metrics", action="store_true")
    parser.add_argument("--process-metrics", action="store_true")
    parser.add_argument("--prefixes", default="")
    parser.add_argument("--out", default="")
    parser.add_argument("--batch", default=os.path.join(WORKSPACE, "DSSBatch.v48"))
    args = parser.parse_args()

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
        out_csv = deterministic_harvest_compare(prefix, args.batch)
        print(f"Deterministic harvest comparison saved to {out_csv}")
    elif args.deterministic_process_compare:
        out_csv = deterministic_process_compare(prefix, args.batch)
        print(f"Deterministic process comparison saved to {out_csv}")
    else:
        analyze(prefix)
