"""Visualize eggplant calibration results."""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import os
import glob

WORKSPACE = os.getcwd()
VIS_DIR = os.path.join(WORKSPACE, "Visualization_Results")
PST_FILE = "eggplant_stage2_v14_full.pst"
PREFIX = "eggplant_stage2_v14_full"

ITER_PRIOR = 0
ITER_POSTERIOR = 6

sns.set_style("whitegrid")
plt.rcParams['font.sans-serif'] = ['Arial']
plt.rcParams['axes.unicode_minus'] = False

if not os.path.exists(VIS_DIR):
    os.makedirs(VIS_DIR)

def load_parameters(iteration):
    file_path = os.path.join(WORKSPACE, f"{PREFIX}.{iteration}.par.csv")
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Parameter file not found: {file_path}")
    df = pd.read_csv(file_path, index_col=0)
    df.columns = [c.upper() for c in df.columns]
    return df

def get_parameter_bounds():
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
                name = parts[0].upper()
                try:
                    lower = float(parts[4])
                    upper = float(parts[5])
                    bounds[name] = (lower, upper)
                except ValueError:
                    continue
    return bounds

def plot_parameter_uncertainty(prior_df, post_df):
    print("Generating Parameter Uncertainty Plot...")
    bounds = get_parameter_bounds()
    print(f"Found bounds for {len(bounds)} parameters.")

    plot_data = []
    common_params = [c for c in prior_df.columns if c in bounds]
    print(f"Plotting parameters: {common_params}")

    if not common_params:
        print("Error: No matching parameters found between CSV and PST.")
        return

    for param in common_params:
        lower, upper = bounds[param]
        span = upper - lower
        if span == 0:
            continue
        norm_prior = (prior_df[param] - lower) / span
        for val in norm_prior:
            plot_data.append({"Parameter": param, "Value": val, "Type": "Prior"})
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

def plot_phi_convergence():
    print("Generating Phi Convergence Plot...")
    phi_file = os.path.join(WORKSPACE, f"{PREFIX}.phi.actual.csv")
    if not os.path.exists(phi_file):
        print(f"Phi file not found: {phi_file}")
        return

    df = pd.read_csv(phi_file)
    if 'iteration' not in df.columns or 'mean' not in df.columns:
        print(f"Phi file does not have expected columns. Columns: {df.columns.tolist()}")
        return

    plt.figure(figsize=(10, 6))
    plt.plot(df['iteration'], df['mean'], marker='o', linewidth=2)
    plt.xlabel('Iteration')
    plt.ylabel('Mean Phi')
    plt.title('Phi Convergence During Calibration')
    plt.grid(True)

    out_file = os.path.join(VIS_DIR, "Phi_Convergence.png")
    plt.savefig(out_file, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Saved: {out_file}")

def plot_obs_uncertainty():
    print("Generating Observation Uncertainty Plot...")
    prior_obs = os.path.join(WORKSPACE, f"{PREFIX}.0.obs.csv")
    post_obs = os.path.join(WORKSPACE, f"{PREFIX}.{ITER_POSTERIOR}.obs.csv")

    if not os.path.exists(prior_obs) or not os.path.exists(post_obs):
        print("Observation files not found.")
        return

    df_prior = pd.read_csv(prior_obs)
    df_post = pd.read_csv(post_obs)

    obs_names = [c for c in df_prior.columns if c.startswith('OBS_') or c.startswith('obs_')]
    if not obs_names:
        obs_names = [c for c in df_prior.columns if 'mean' in c.lower()]

    if not obs_names:
        print(f"No observation columns found in prior obs file. Columns: {df_prior.columns.tolist()}")
        return

    print(f"Found observation columns: {obs_names[:5]}...")

    plot_data = []
    for obs in obs_names:
        if obs in df_prior.columns and obs in df_post.columns:
            prior_vals = df_prior[obs].dropna()
            post_vals = df_post[obs].dropna()
            for val in prior_vals:
                plot_data.append({"Observation": obs[:20], "Value": val, "Type": "Prior"})
            for val in post_vals:
                plot_data.append({"Observation": obs[:20], "Value": val, "Type": "Posterior"})

    if plot_data:
        df_plot = pd.DataFrame(plot_data)
        plt.figure(figsize=(14, 6))
        sns.boxplot(data=df_plot, x="Observation", y="Value", hue="Type",
                    palette={"Prior": "lightgray", "Posterior": "#3498db"})
        plt.title("Observation Uncertainty Reduction")
        plt.xticks(rotation=45)
        out_file = os.path.join(VIS_DIR, "Observation_Uncertainty.png")
        plt.savefig(out_file, dpi=300, bbox_inches='tight')
        plt.close()
        print(f"Saved: {out_file}")

def plot_parameter_change_summary():
    print("Generating Parameter Change Summary...")
    pcs_file = os.path.join(WORKSPACE, f"{PREFIX}.{ITER_POSTERIOR}.pcs.csv")
    if not os.path.exists(pcs_file):
        print(f"PCS file not found: {pcs_file}")
        return

    df = pd.read_csv(pcs_file)
    print(f"PCS columns: {df.columns.tolist()}")

    if 'group' not in df.columns:
        print("PCS file does not have 'group' column.")
        return

    plt.figure(figsize=(10, 6))
    groups = df['group'].unique()
    for grp in groups:
        grp_data = df[df['group'] == grp]
        plt.scatter(grp_data.get('mean_chg', [0]), [grp]*len(grp_data), s=100, label=grp)

    plt.xlabel('Mean Change')
    plt.ylabel('Parameter Group')
    plt.title('Parameter Changes by Group')
    plt.legend()
    out_file = os.path.join(VIS_DIR, "Parameter_Change_Summary.png")
    plt.savefig(out_file, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Saved: {out_file}")

def main():
    print(f"Visualizing {PREFIX} calibration results")
    print(f"Working directory: {WORKSPACE}")
    print(f"Visualization output: {VIS_DIR}")

    try:
        prior_df = load_parameters(ITER_PRIOR)
        print(f"Loaded prior parameters: {prior_df.shape}")
    except Exception as e:
        print(f"Error loading prior parameters: {e}")
        prior_df = None

    try:
        post_df = load_parameters(ITER_POSTERIOR)
        print(f"Loaded posterior parameters: {post_df.shape}")
    except Exception as e:
        print(f"Error loading posterior parameters: {e}")
        post_df = None

    if prior_df is not None and post_df is not None:
        plot_parameter_uncertainty(prior_df, post_df)
    else:
        print("Skipping parameter uncertainty plot due to missing data.")

    plot_phi_convergence()
    plot_obs_uncertainty()
    plot_parameter_change_summary()

    print("\nVisualization complete!")
    print(f"Output files saved to: {VIS_DIR}")
    for f in glob.glob(os.path.join(VIS_DIR, "*.png")):
        print(f"  - {os.path.basename(f)}")

if __name__ == "__main__":
    main()