import pandas as pd
import numpy as np

run_dir = "workspace/runs/full_gen_13trt_final_opt_150x5_20260922"
phi_df = pd.read_csv(f"{run_dir}/full_gen_13trt_final_opt_150x5_20260922.phi.actual.csv")
par_df5 = pd.read_csv(f"{run_dir}/full_gen_13trt_final_opt_150x5_20260922.5.par.csv")
bounds_df = pd.read_csv("data/parameter_registry/bounds_frozen/eggplant/eggplant_full_gen_final_opt_13trt_20260922.csv")

print("=== Phi Convergence ===")
print(phi_df[["iteration", "total_runs", "mean", "standard_deviation", "min", "max"]].to_string(index=False))

# Identify best member in Iteration 5
iter5_phis = phi_df.iloc[-1].drop(["iteration", "total_runs", "mean", "standard_deviation", "min", "max"]).dropna().astype(float)
best_real = iter5_phis.idxmin()
best_phi = iter5_phis.min()
print(f"\nBest realization in Iteration 5: {best_real} with Phi = {best_phi:.3f}")

best_par_row = par_df5[par_df5.iloc[:, 0].astype(str) == str(best_real)].iloc[0]

target_params = [
    "kcan", "sizlf", "dswbar", "thrsh", "tb1",
    "slaref", "sizref", "sasc_ratio", "icns_25sp", "icns_26sp",
    "prolff", "prolfg", "prolfi",
    "prostf", "prostg", "prosti",
    "prortf", "prortg", "prorti",
    "proshg", "proshi",
    "optlfp_fs", "optstp_fs", "optsdp_fs",
    "xfrt", "xmage", "podur", "sfdur", "em-fl", "fl-lf", "fl-sd", "fl-sh",
    "pgeff", "fnpgn1", "fnpgn2", "fnpgn3", "fnpgn4", "nmobmx", "lnref"
]

print(f"\n=== Best Parameter Values (Realization {best_real}, Phi={best_phi:.3f}) ===")
header = f"{'Parameter':<15} | {'Value':<12} | {'Lower':<10} | {'Upper':<10} | {'Status':<8} | {'Position (%)':<12}"
print(header)
print("-" * len(header))

for p in target_params:
    b_match = bounds_df[bounds_df["name"].str.lower() == p.lower()]
    if len(b_match) == 0:
        continue
    b_row = b_match.iloc[0]
    p_name_bounds = b_row["name"]

    val = None
    for col in par_df5.columns:
        if col.strip().lower() == p.lower():
            val = float(best_par_row[col])
            break

    lower = float(b_row["lower"])
    upper = float(b_row["upper"])
    status = b_row["status"]

    if val is not None:
        if upper > lower:
            pos = (val - lower) / (upper - lower) * 100
            pos_str = f"{pos:6.1f}%"
        else:
            pos_str = "fixed"
        print(f"{p_name_bounds:<15} | {val:<12.5g} | {lower:<10.5g} | {upper:<10.5g} | {status:<8} | {pos_str:<12}")
    else:
        print(f"{p_name_bounds:<15} | {'N/A':<12} | {lower:<10.5g} | {upper:<10.5g} | {status:<8} | {'N/A':<12}")
