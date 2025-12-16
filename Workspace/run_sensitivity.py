import os
import shutil
import pyemu
import subprocess
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np

# Configuration
WORKSPACE = r"C:\DSSAT48\Tomato_Cal\Workspace"
RESULTS_DIR = os.path.join(WORKSPACE, "Sensitivity_Results")
PST_FILE_ORIG = os.path.join(WORKSPACE, "tomato_cal.pst")
PST_FILE_SEN = os.path.join(WORKSPACE, "tomato_sen.pst")
PESTPP_SEN_EXE = r"c:\DSSAT48\Tomato_Cal\pestpp-5.2.16-win\bin\pestpp-sen.exe"

# Font Configuration for "Xiao Wu" (approx 9pt) and Journal Standards
plt.rcParams['font.family'] = 'Times New Roman'
plt.rcParams['font.size'] = 9
plt.rcParams['axes.labelsize'] = 9
plt.rcParams['xtick.labelsize'] = 8
plt.rcParams['ytick.labelsize'] = 8
plt.rcParams['legend.fontsize'] = 8
plt.rcParams['figure.dpi'] = 300
plt.rcParams['savefig.dpi'] = 600

def ensure_results_dir():
    if not os.path.exists(RESULTS_DIR):
        os.makedirs(RESULTS_DIR)
        print(f"Created results directory: {RESULTS_DIR}")

def setup_sensitivity_pst(method="morris", sample_size=10):
    """
    Configures a PEST control file for Global Sensitivity Analysis (GSA).
    """
    print(f"Configuring {PST_FILE_SEN} for GSA method: {method} with sample_size: {sample_size}")
    
    # Load the existing control file
    pst = pyemu.Pst(PST_FILE_ORIG)
    
    # Clear existing options to avoid conflicts
    pst.pestpp_options = {} 
    
    # Set GSA options
    pst.pestpp_options["gsa_method"] = method
    
    if method == "morris":
        pst.pestpp_options["gsa_morris_r"] = sample_size
        pst.pestpp_options["gsa_morris_p"] = 4 # Default levels
    elif method == "sobol":
        pst.pestpp_options["gsa_sobol_samples"] = sample_size
    
    # Ensure noptmax is -1 (exploration only)
    pst.control_data.noptmax = -1 
    
    # Write to new file
    pst.write(PST_FILE_SEN)
    print(f"Sensitivity control file written to {PST_FILE_SEN}")

def run_sensitivity():
    # Ensure pestpp-sen exists
    if not os.path.exists(PESTPP_SEN_EXE):
        raise FileNotFoundError(f"pestpp-sen.exe not found at {PESTPP_SEN_EXE}")
        
    print(f"Running PEST++ Sensitivity Analysis...")
    print(f"Executable: {PESTPP_SEN_EXE}")
    print(f"Control File: {PST_FILE_SEN}")
    
    # Run command
    cmd = [PESTPP_SEN_EXE, "tomato_sen.pst"]
    
    # Execute with live output
    process = subprocess.Popen(cmd, cwd=WORKSPACE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    # Stream output
    while True:
        output = process.stdout.readline()
        if output == '' and process.poll() is not None:
            break
        if output:
            print(output.strip())
            
    rc = process.poll()
    if rc != 0:
        print(f"Error: pestpp-sen exited with code {rc}")
        stderr_output = process.stderr.read()
        print(stderr_output)
    else:
        print("Sensitivity analysis completed successfully.")
        analyze_sen_results()

def plot_morris_results(df, output_dir):
    """
    Generates publication-quality plots for Morris analysis.
    1. Horizontal Bar Chart (Ranking)
    2. Morris Plot (Sigma vs Mu*)
    """
    # Prepare data
    df = df.sort_values(by='sen_mean_abs', ascending=True) # Ascending for barh
    
    # Standardize column names for plotting
    std_col = 'sen_std_dev' if 'sen_std_dev' in df.columns else 'sen_std'
    
    # --- Plot 1: Sensitivity Ranking (Bar Chart) ---
    fig, ax = plt.subplots(figsize=(6, 4)) # Width, Height in inches (single column width)
    
    # Create gradient color based on sensitivity
    norm = plt.Normalize(df['sen_mean_abs'].min(), df['sen_mean_abs'].max())
    colors = plt.cm.viridis(norm(df['sen_mean_abs'].values))
    
    bars = ax.barh(df['parameter_name'], df['sen_mean_abs'], color=colors, edgecolor='black', linewidth=0.5)
    
    ax.set_xlabel('Mean Absolute Sensitivity ($\mu^*$)', fontweight='bold')
    ax.set_ylabel('Parameters', fontweight='bold')
    ax.set_title('Parameter Sensitivity Ranking (Morris Method)', fontsize=10, fontweight='bold', pad=10)
    
    # Grid and style
    ax.grid(axis='x', linestyle='--', alpha=0.7)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    
    # Add value labels
    for bar in bars:
        width = bar.get_width()
        ax.text(width * 1.02, bar.get_y() + bar.get_height()/2, 
                f'{width:.2e}', 
                va='center', fontsize=7, color='black')
        
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "Morris_Ranking_BarPlot.png"), dpi=600, bbox_inches='tight')
    plt.savefig(os.path.join(output_dir, "Morris_Ranking_BarPlot.pdf"), bbox_inches='tight')
    plt.close()

    # --- Plot 2: Morris Plot (Interaction vs Influence) ---
    fig, ax = plt.subplots(figsize=(6, 5))
    
    # Scatter plot
    sns.scatterplot(data=df, x='sen_mean_abs', y=std_col, 
                    hue='sen_mean_abs', palette='viridis', legend=False, 
                    s=100, edgecolor='black', alpha=0.8, ax=ax)
    
    # Diagonal line (Sigma = Mu*) - often used as a reference for linearity
    # But usually just dividing lines are better.
    # Let's add text labels
    for i, row in df.iterrows():
        ax.text(row['sen_mean_abs'], row[std_col], 
                f" {row['parameter_name']}", 
                fontsize=8, ha='left', va='bottom')
        
    ax.set_xlabel('Influence: Mean Absolute Sensitivity ($\mu^*$)', fontweight='bold')
    ax.set_ylabel('Interaction/Non-linearity: Standard Deviation ($\sigma$)', fontweight='bold')
    ax.set_title('Morris Sensitivity Analysis: Influence vs. Interaction', fontsize=10, fontweight='bold', pad=10)
    
    # Add wedges/lines to separate regions
    mean_mu = df['sen_mean_abs'].mean()
    mean_sigma = df[std_col].mean()
    
    ax.axvline(mean_mu, color='gray', linestyle='--', alpha=0.5, linewidth=0.8)
    ax.axhline(mean_sigma, color='gray', linestyle='--', alpha=0.5, linewidth=0.8)
    
    # Annotate Quadrants
    # Top Right: High Influence, High Interaction
    # Bottom Right: High Influence, Low Interaction (Linear)
    
    ax.grid(True, linestyle=':', alpha=0.6)
    
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "Morris_Interaction_Scatter.png"), dpi=600, bbox_inches='tight')
    plt.savefig(os.path.join(output_dir, "Morris_Interaction_Scatter.pdf"), bbox_inches='tight')
    plt.close()
    
    print(f"Plots saved to {output_dir}")

def analyze_sen_results():
    """
    Reads and displays the sensitivity results.
    """
    ensure_results_dir()
    
    # File name depends on method
    # Morris -> .msn
    msn_file = os.path.join(WORKSPACE, "tomato_sen.msn")
    
    if os.path.exists(msn_file):
        print("\n--- Morris Sensitivity Analysis Results (Top 10) ---")
        try:
            # The .msn file is usually CSV-like
            df = pd.read_csv(msn_file)
            # Clean column names
            df.columns = [c.strip().lower() for c in df.columns]
            
            if 'sen_mean_abs' in df.columns:
                df_sorted = df.sort_values(by='sen_mean_abs', ascending=False)
                # Check for correct std dev column name
                std_col = 'sen_std_dev' if 'sen_std_dev' in df.columns else 'sen_std'
                
                print(df_sorted[['parameter_name', 'sen_mean_abs', std_col]].head(10))
                
                # Save simplified report to Results Directory
                report_file = os.path.join(RESULTS_DIR, "sensitivity_report_morris.csv")
                df_sorted.to_csv(report_file, index=False)
                print(f"\nFull report saved to {report_file}")
                
                # Copy raw .msn file for backup
                shutil.copy2(msn_file, os.path.join(RESULTS_DIR, "tomato_sen_raw.msn"))
                
                # Generate Plots
                plot_morris_results(df_sorted, RESULTS_DIR)
                
            else:
                print("Could not find 'sen_mean_abs' column. Raw columns:", df.columns)
                print(df.head())
        except Exception as e:
            print(f"Error analyzing results: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    # Ensure base PST is built
    if not os.path.exists(PST_FILE_ORIG):
        print("Base PST file not found. Running build_pest.py...")
        subprocess.run(["python", "build_pest.py"], cwd=WORKSPACE)
        
    # Run Morris Method with 6 trajectories (reasonable for screening)
    setup_sensitivity_pst(method="morris", sample_size=6) 
    run_sensitivity()
