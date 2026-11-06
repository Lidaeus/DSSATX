import pandas as pd

df = pd.read_csv("subprojects/critical_n/reports/official_vs_stage_r4_vs_enhanced_metrics.csv")
key_vars = ["CHFPW", "CHPDT", "LAID", "LWAD", "SWAD", "LEAF_N_PCT", "STEM_N_PCT", "VWC"]
for season in ["26SP", "25SP", "25FA"]:
    print(f"\n=== {season} ===")
    sub = df[df["season_id"] == season]
    for v in key_vars:
        rows = sub[sub["variable"] == v]
        for _, r in rows.iterrows():
            role = r["dataset_role"]
            print(
                f"{v:11s} [{role[:4]}] | "
                f"NRMSE: Off={r['nrmse_official']:5.1f}%, R4={r['nrmse_stage_r4']:5.1f}%, Enh={r['nrmse_enhanced']:5.1f}% | "
                f"NSE: Off={r['nse_official']:6.2f}, R4={r['nse_stage_r4']:6.2f}, Enh={r['nse_enhanced']:6.2f} | "
                f"d: Off={r['d_official']:5.3f}, R4={r['d_stage_r4']:5.3f}, Enh={r['d_enhanced']:5.3f}"
            )
