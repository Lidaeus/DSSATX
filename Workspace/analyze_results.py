import argparse
import pandas as pd
import numpy as np
import os
import glob
import pyemu
import shutil

WORKSPACE = r"C:\DSSAT48\Tomato_Cal\Workspace"
RESULTS_DIR = os.path.join(WORKSPACE, "Calibration_Results")

def ensure_results_dir():
    if not os.path.exists(RESULTS_DIR):
        os.makedirs(RESULTS_DIR)
        print(f"Created results directory: {RESULTS_DIR}")

def get_ensemble_files(pattern):
    """
    Finds files matching pattern in both RESULTS_DIR and WORKSPACE.
    Returns combined list of files.
    """
    files_res = glob.glob(os.path.join(RESULTS_DIR, pattern))
    files_wksp = glob.glob(os.path.join(WORKSPACE, pattern))
    return files_res + files_wksp

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
        # tomato_cal.0.obs.csv -> parts[1] is '0'
        # Check if parts[1] is a digit
        if len(parts) >= 4 and parts[1].isdigit():
            iter_files.append((int(parts[1]), f))
            
    if not iter_files:
        print("No observation ensemble files found!")
        return

    # Sort by iteration
    iter_files.sort(key=lambda x: x[0])
    latest_iter, latest_file = iter_files[-1]
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
            par_iter_files.append((int(parts[1]), f))
    
    if par_iter_files:
        par_iter_files.sort(key=lambda x: x[0])
        latest_par_iter, latest_par_file = par_iter_files[-1]
        print(f"\nAnalyzing parameters from iteration {latest_par_iter}...")
        
        par_ens = pd.read_csv(latest_par_file, index_col=0)
        
        # 1. Uncertainty Statistics
        par_stats = par_ens.describe(percentiles=[0.025, 0.975]).T
        par_stats['mean'] = par_ens.mean()
        
        par_output_path = os.path.join(RESULTS_DIR, f"{prefix}_parameter_uncertainty.csv")
        par_stats.to_csv(par_output_path)
        print(f"Parameter uncertainty saved to {par_output_path}")

        # 2. Identify Best Realization (Minimum Phi)
        # Check RESULTS_DIR first, then WORKSPACE
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

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", default="tomato_cal")
    args = parser.parse_args()
    analyze((args.prefix or "tomato_cal").strip())
