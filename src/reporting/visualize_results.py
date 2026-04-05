import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import os
import glob
import subprocess
import shutil

# --- Configuration ---
WORKSPACE = os.getcwd()
CALIB_DIR = os.path.join(WORKSPACE, "Calibration_Results")
VIS_DIR = os.path.join(WORKSPACE, "Visualization_Results")
PST_FILE = "tomato_cal.pst"

# Iterations to compare
ITER_PRIOR = 0
ITER_POSTERIOR = 12  # Adjust if needed based on available files

# Plot Settings
sns.set_style("whitegrid")
plt.rcParams['font.sans-serif'] = ['Arial']
plt.rcParams['axes.unicode_minus'] = False

if not os.path.exists(VIS_DIR):
    os.makedirs(VIS_DIR)

def load_parameters(iteration):
    """Load parameter ensemble for a specific iteration."""
    file_path = os.path.join(CALIB_DIR, f"tomato_cal.{iteration}.par.csv")
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Parameter file not found: {file_path}")
    
    df = pd.read_csv(file_path, index_col=0)
    # Normalize column names to uppercase to match PST
    df.columns = [c.upper() for c in df.columns]
    return df

def get_parameter_bounds():
    """Extract parameter bounds from PST file (simplistic parsing)."""
    bounds = {}
    with open(PST_FILE, 'r') as f:
        lines = f.readlines()
    
    print(f"Read {len(lines)} lines from {PST_FILE}")
    
    in_param_section = False
    for line in lines:
        line_lower = line.lower()
        if "parameter data" in line_lower and "*" in line_lower:
            in_param_section = True
            print("Entered parameter section")
            continue
        if "observation" in line_lower and "*" in line_lower:
            in_param_section = False
        
        if in_param_section:
            parts = line.strip().split()
            if len(parts) >= 6:
                name = parts[0].upper() # Normalize to uppercase
                # print(f"Parsing param: {name}") # Debug
                # PEST format: name trans chg_lim val lower_bound upper_bound group scale offset
                # Assuming standard format
                try:
                    lower = float(parts[4])
                    upper = float(parts[5])
                    bounds[name] = (lower, upper)
                except ValueError:
                    continue
    return bounds

def plot_parameter_uncertainty(prior_df, post_df):
    """Plot Split Violin Plot for parameter uncertainty."""
    print("Generating Parameter Uncertainty Plot...")
    
    bounds = get_parameter_bounds()
    print(f"Found bounds for {len(bounds)} parameters.")
    
    # Normalize data
    plot_data = []
    
    common_params = [c for c in prior_df.columns if c in bounds]
    print(f"Plotting parameters: {common_params}")

    if not common_params:
        print("Error: No matching parameters found between CSV and PST.")
        return
    
    for param in common_params:
        lower, upper = bounds[param]
        span = upper - lower
        if span == 0: continue
        
        # Normalize Prior
        norm_prior = (prior_df[param] - lower) / span
        for val in norm_prior:
            plot_data.append({"Parameter": param, "Value": val, "Type": "Prior"})
            
        # Normalize Posterior
        norm_post = (post_df[param] - lower) / span
        for val in norm_post:
            plot_data.append({"Parameter": param, "Value": val, "Type": "Posterior"})
            
    df_plot = pd.DataFrame(plot_data)
    
    plt.figure(figsize=(14, 8))
    sns.violinplot(data=df_plot, x="Parameter", y="Value", hue="Type", 
                   split=True, inner="quart", palette={"Prior": "lightgray", "Posterior": "#2ecc71"})
    
    plt.ylim(-0.2, 1.2)
    plt.ylabel("Normalized Parameter Value (0=Lower Bound, 1=Upper Bound)")
    plt.title("Parameter Uncertainty Reduction (Prior vs Posterior)", fontsize=16)
    plt.xticks(rotation=45)
    
    out_file = os.path.join(VIS_DIR, "Parameter_Uncertainty_Violin.png")
    plt.savefig(out_file, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Saved: {out_file}")

def plot_correlation_matrix(post_df):
    """Plot Spearman Correlation Heatmap."""
    print("Generating Correlation Matrix...")
    
    # Filter out fixed parameters (std dev = 0)
    valid_cols = [c for c in post_df.columns if post_df[c].std() > 1e-6]
    df_filtered = post_df[valid_cols]
    
    corr = df_filtered.corr(method='spearman')
    
    plt.figure(figsize=(12, 10))
    sns.heatmap(corr, annot=True, fmt=".2f", cmap="coolwarm", vmin=-1, vmax=1, center=0,
                square=True, linewidths=.5, cbar_kws={"shrink": .5})
    
    plt.title("Parameter Correlation Matrix (Posterior)", fontsize=16)
    
    out_file = os.path.join(VIS_DIR, "Parameter_Correlation_Matrix.png")
    plt.savefig(out_file, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Saved: {out_file}")

# --- Posterior Prediction Section ---

def parse_t_file(t_file):
    """Parse DSSAT .T file for observed time series."""
    data = []
    with open(t_file, 'r') as f:
        lines = f.readlines()
    
    header = None
    for line in lines:
        if line.startswith('@'):
            header = line.strip().split()
            # Clean up header names (remove @ from TRNO)
            header = [h.replace('@', '') for h in header]
            continue
        if line.startswith('!') or len(line.strip()) == 0:
            continue
        if header:
            # Fixed width parsing is safer, but split() often works for DSSAT
            parts = line.strip().split()
            if len(parts) == len(header):
                row = dict(zip(header, parts))
                data.append(row)
    
    df = pd.DataFrame(data)
    # Convert types
    numeric_cols = ['DATE', 'LAID', 'CWAD'] # Add others if needed
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
            
    return df

def run_posterior_ensemble(post_df, sample_size=50):
    """Run a subset of posterior parameters to get time series."""
    print(f"Running Posterior Ensemble (N={sample_size})... This may take a while.")
    
    # Randomly sample
    if len(post_df) > sample_size:
        subset = post_df.sample(n=sample_size, random_state=42)
    else:
        subset = post_df
        
    results = []
    
    total = len(subset)
    for i, (idx, row) in enumerate(subset.iterrows()):
        print(f"  Running realization {i+1}/{total}...", end="\r")
        
        # 1. Write params
        # Need to format specifically as expected by run_dssat.py/tpl
        # Actually run_dssat.py reads pest_params.csv which is a simple header+value row?
        # Let's check format. usually header, then values.
        row.to_frame().T.to_csv("pest_params.csv", index=False)
        
        # 2. Run DSSAT
        # We assume run_dssat.py is in the current directory
        proc = subprocess.run(["python", "run_dssat.py"], capture_output=True, text=True)
        
        if proc.returncode != 0:
            print(f"  Warning: Run {i} failed.")
            continue
            
        # 3. Read PlantGro.OUT
        if os.path.exists("PlantGro.OUT"):
            try:
                # PlantGro.OUT has a header line starting with @
                # Skip lines until @
                with open("PlantGro.OUT", 'r') as f:
                    lines = f.readlines()
                
                header_line = None
                start_idx = 0
                for j, line in enumerate(lines):
                    if line.startswith('@'):
                        header_line = line
                        start_idx = j + 1
                        break
                
                if header_line:
                    cols = header_line.split()
                    # Remove @ from first column if present
                    cols = [c.replace('@', '') for c in cols]
                    
                    data_rows = []
                    for line in lines[start_idx:]:
                        parts = line.split()
                        if len(parts) == len(cols):
                            data_rows.append(parts)
                    
                    pg_df = pd.DataFrame(data_rows, columns=cols)
                    # Convert types
                    pg_df = pg_df.apply(pd.to_numeric, errors='coerce')
                    
                    # Add identifiers
                    pg_df['Realization'] = i
                    results.append(pg_df)
            except Exception as e:
                print(f"  Error reading PlantGro: {e}")
                
    print("\nEnsemble run complete.")
    if results:
        return pd.concat(results, ignore_index=True)
    return pd.DataFrame()

def plot_time_series(ensemble_df, obs_df, variable='LAID', sim_variable='LAID', title="Time Series"):
    """Plot ensemble time series with confidence intervals."""
    print(f"Generating Time Series Plot for {variable}...")
    
    # Calculate stats per DATE and TRNO
    # Usually PlantGro has DOY (Day of Year) as 'DOY' or 'DAP'
    # obs_df has 'DATE' (YYDDD)
    # PlantGro has 'YEAR' and 'DOY'. Construct DATE = YEAR*1000 + DOY ?
    # Let's check PlantGro cols. Usually @YEAR DOY ...
    
    if 'DOY' not in ensemble_df.columns:
        print("Error: DOY column not found in ensemble results.")
        return

    # Convert ensemble dates to match obs dates (YYDDD)
    # Assuming standard DSSAT output: YEAR (4 digits), DOY (1-366)
    if 'YEAR' in ensemble_df.columns:
        ensemble_df['DATE'] = (ensemble_df['YEAR'] % 100) * 1000 + ensemble_df['DOY']
    
    # Filter for valid data
    ensemble_df = ensemble_df[ensemble_df[sim_variable] > -99]
    
    # Group by DATE (and Treatment if mixed, but assume single treatment/experiment for now or filter)
    # If multiple treatments, we should loop. 
    # For now, let's assume Treatment 1 or the one in the file.
    # obs_df has 'TRNO'.
    
    unique_treatments = obs_df['TRNO'].unique()
    
    for trt in unique_treatments:
        trt_ens = ensemble_df # Assuming the run was for this treatment. 
        # Wait, run_dssat.py runs ALL treatments defined in DSSBatch.v48.
        # PlantGro.OUT contains output for ALL runs sequentially.
        # It usually has 'RUN' column? No, standard PlantGro doesn't always have RUN if it's concatenated.
        # But if DSSAT runs in batch mode, PlantGro appends.
        # Let's verify PlantGro structure later.
        # Assuming run_dssat.py cleans and runs, PlantGro might contain data for Run 1, then Run 2...
        # We need to distinguish treatments.
        # Standard PlantGro has 'TRNO' column if generated by recent DSSAT versions?
        # If not, we rely on 'RUN'.
        
        # Let's skip complex treatment handling and plot what we have if it matches dates.
        
        trt_obs = obs_df[obs_df['TRNO'] == trt]
        
        # Aggregate ensemble stats
        stats = trt_ens.groupby('DATE')[sim_variable].agg(
            mean='mean',
            lower=lambda x: np.percentile(x, 2.5),
            upper=lambda x: np.percentile(x, 97.5)
        ).reset_index()
        
        plt.figure(figsize=(12, 6))
        
        # Plot 95% CI
        plt.fill_between(stats['DATE'], stats['lower'], stats['upper'], color='green', alpha=0.3, label='95% CI')
        # Plot Mean
        plt.plot(stats['DATE'], stats['mean'], color='darkgreen', linewidth=2, label='Ensemble Mean')
        
        # Plot Observations
        plt.scatter(trt_obs['DATE'], trt_obs[variable], color='red', marker='o', label='Observed')
        
        plt.xlabel("Date (YYDDD)")
        plt.ylabel(title)
        plt.title(f"{title} - Treatment {trt} (Ensemble N={len(ensemble_df['Realization'].unique())})")
        plt.legend()
        
        out_file = os.path.join(VIS_DIR, f"TimeSeries_{variable}_TRT{trt}.png")
        plt.savefig(out_file, dpi=300)
        plt.close()
        print(f"Saved: {out_file}")

# --- Main ---

def main():
    print("Starting Visualization Workflow...")
    
    # 1. Load Parameters
    try:
        prior_df = load_parameters(ITER_PRIOR)
        post_df = load_parameters(ITER_POSTERIOR)
        print(f"Loaded Prior: {len(prior_df)} samples, Posterior: {len(post_df)} samples")
    except Exception as e:
        print(f"Error loading parameters: {e}")
        return

    # 2. Plot Uncertainty & Correlations
    plot_parameter_uncertainty(prior_df, post_df)
    plot_correlation_matrix(post_df)
    
    # 3. Posterior Predictive Checks (Time Series)
    # Check if we should run this (it takes time)
    # For now, we run it for N=20 to demonstrate quickly. User can increase.
    
    # Load observed data to find available variables
    # Assuming UFBR9401.TMT is the main one. In reality we should check all .T files or the one corresponding to the run.
    t_files = glob.glob("*.TMT") + glob.glob("*.TMA") # or just *.T*
    if not t_files:
        print("No .T files found for observation comparison.")
        return
    
    # Pick the first one for demo
    obs_file = "UFBR9401.TMT"
    if os.path.exists(obs_file):
        obs_df = parse_t_file(obs_file)
        
        # Run Ensemble
        # Increase sample size for better plots if time permits, but 20 is fast for testing.
        ensemble_df = run_posterior_ensemble(post_df, sample_size=50) 
        
        if not ensemble_df.empty:
            # Plot LAI
            if 'LAID' in obs_df.columns and 'LAID' in ensemble_df.columns:
                plot_time_series(ensemble_df, obs_df, variable='LAID', sim_variable='LAID', title="Leaf Area Index")
            
            # Plot Biomass (CWAD vs CWAD)
            if 'CWAD' in obs_df.columns and 'CWAD' in ensemble_df.columns:
                plot_time_series(ensemble_df, obs_df, variable='CWAD', sim_variable='CWAD', title="Top Weight (Biomass)")
                
    print("Visualization Complete.")

if __name__ == "__main__":
    main()
