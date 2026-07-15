import pandas as pd
import sys
import os

WORKSPACE = r"d:\Tomato_Cal\workspace"
PREFIX = "eggplant_stage2_v14_full"
ITER = 6

par_csv = os.path.join(WORKSPACE, f"{PREFIX}.{ITER}.par.csv")
phi_csv = os.path.join(WORKSPACE, f"{PREFIX}.phi.actual.csv")

df_par = pd.read_csv(par_csv, index_col=0)
df_phi = pd.read_csv(phi_csv)

iter_row = df_phi[df_phi['iteration'] == ITER].iloc[0]

real_cols = [c for c in df_phi.columns if c.isdigit()]
phi_values = iter_row[real_cols].astype(float)

best_real = phi_values.idxmin()
best_phi = phi_values.min()

print(f"Best realization: {best_real} with phi={best_phi:.4f}")

best_params = df_par.loc[best_real]

param_csv = os.path.join(WORKSPACE, f"{PREFIX}_best_params.csv")
best_params.to_csv(param_csv)
print(f"Saved best parameters to {param_csv}")

print(f"\nBest parameters for realization {best_real}:")
for name, value in best_params.items():
    print(f"  {name}: {value}")