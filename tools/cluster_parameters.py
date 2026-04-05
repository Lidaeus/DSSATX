import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.manifold import TSNE
from sklearn.metrics import pairwise_distances_argmin_min
import os

# Configuration
WORKSPACE = r"c:\DSSAT48\Tomato_Cal\Workspace"
INPUT_FILE = os.path.join(WORKSPACE, "Calibration_Results", "tomato_cal.12.par.csv")
OUTPUT_DIR = os.path.join(WORKSPACE, "Visualization_Results")
OUTPUT_CSV = os.path.join(OUTPUT_DIR, "Representative_Parameters.csv")
OUTPUT_SVG = os.path.join(OUTPUT_DIR, "Cluster_Visualization.svg")

# Ensure output directory exists
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

def main():
    print("Starting Clustering Analysis...")
    
    # 1. Load Data
    if not os.path.exists(INPUT_FILE):
        print(f"Error: Input file not found at {INPUT_FILE}")
        return

    # Load parameter ensemble
    # Note: PEST++ outputs typically have 'real_name' as the first column/index
    df = pd.read_csv(INPUT_FILE, index_col=0)
    print(f"Loaded {len(df)} parameter sets.")
    
    # Filter out any non-numeric columns if present (though index_col=0 usually handles real_name)
    # Also, ensure we only cluster on parameters, not other stats if present.
    # Assuming all columns in .par.csv are parameters.
    
    # 2. Standardization
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(df)
    
    # 3. K-Means Clustering
    n_clusters = 9
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    df['Cluster'] = kmeans.fit_predict(X_scaled)
    
    print(f"Performed K-Means clustering with k={n_clusters}.")
    
    # 4. Find Representative Samples (Closest to Centroid)
    representatives_indices = []
    representatives_data = []
    
    centroids = kmeans.cluster_centers_
    
    # We need to find the point in X_scaled that is closest to each centroid
    closest_indices, _ = pairwise_distances_argmin_min(centroids, X_scaled)
    
    for i, idx in enumerate(closest_indices):
        real_name = df.index[idx]
        print(f"Cluster {i} Representative: Realization {real_name}")
        
        # Get the row from original df (with parameters)
        row = df.iloc[idx].copy()
        row['Representative_For_Cluster'] = i
        representatives_data.append(row)
        representatives_indices.append(idx)

    # Save Representative Parameters
    rep_df = pd.DataFrame(representatives_data)
    # Reorder columns to put cluster info first
    cols = ['Cluster', 'Representative_For_Cluster'] + [c for c in rep_df.columns if c not in ['Cluster', 'Representative_For_Cluster']]
    rep_df = rep_df[cols]
    
    rep_df.to_csv(OUTPUT_CSV)
    print(f"Saved representative parameters to {OUTPUT_CSV}")
    
    # 5. Visualization (t-SNE)
    print("Running t-SNE...")
    # Perplexity should be less than number of samples. 30 is default, but for ~100 samples it's fine.
    # max_iter=1000 is usually enough for convergence.
    tsne = TSNE(n_components=2, random_state=42, perplexity=30)
    X_tsne = tsne.fit_transform(X_scaled)

    # Create a DataFrame for plotting
    plot_tsne_df = pd.DataFrame(X_tsne, columns=['Dim1', 'Dim2'])
    # Assign cluster values directly to avoid index mismatch
    plot_tsne_df['Cluster'] = df['Cluster'].values.astype(str)
    plot_tsne_df['Type'] = 'Ensemble'

    # Mark representatives
    plot_tsne_df.iloc[closest_indices, plot_tsne_df.columns.get_loc('Type')] = 'Representative'

    title_tsne = "K-Means Clustering of Top 100 Parameters (t-SNE Projection)"

    # Plotting
    plt.figure(figsize=(12, 8))

    # Plot all points (Ensemble)
    # Filter out representatives to plot them separately if needed, but here we plot everything.
    # To ensure visibility, we can plot using plt.scatter first for the background points
    
    # Define colors manually or via seaborn
    unique_clusters = sorted(plot_tsne_df['Cluster'].unique())
    colors = sns.color_palette('viridis', n_colors=len(unique_clusters))
    cluster_color_map = dict(zip(unique_clusters, colors))
    
    for clust in unique_clusters:
        subset = plot_tsne_df[plot_tsne_df['Cluster'] == clust]
        plt.scatter(
            subset['Dim1'], 
            subset['Dim2'], 
            c=[cluster_color_map[clust]], 
            label=f'Cluster {clust}',
            s=20, # Smaller dots for background points
            alpha=0.8,
            edgecolors='none' # No border for cleaner look
        )

    # Highlight representatives specifically with larger size/border
    rep_points_tsne = plot_tsne_df.iloc[closest_indices]
    plt.scatter(
        rep_points_tsne['Dim1'],
        rep_points_tsne['Dim2'],
        s=100, # Same size as other points to match style 1
        c='red', # Filled with red
        edgecolors='black', # Black border
        linewidth=1,
        label='Representative Center',
        zorder=10 # Ensure on top
    )

    plt.title(title_tsne, fontsize=15)
    plt.xlabel("t-SNE Dimension 1")
    plt.ylabel("t-SNE Dimension 2")
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.grid(True, linestyle='--', alpha=0.5)

    plt.tight_layout()
    plt.savefig(OUTPUT_SVG, format='svg')
    print(f"Saved t-SNE clustering visualization to {OUTPUT_SVG}")

if __name__ == "__main__":
    main()
