import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.reporting.analyze_results import deterministic_process_compare
from tools.eval_full_gen98 import calc_metrics, evaluate_run

def main():
    p = ROOT / "workspace" / "runs" / "full_gen_page22_sasc0925_150x5_20260918"
    dir_25sp = p / "full_season_iter5_real13_25SP"
    dir_26sp = p / "full_season_iter5_real13_26SP"
    dir_25fa = p / "cand_iter5_real13_25fa"

    proc_vars = ["LAID", "LWAD", "SWAD", "CHTD", "L#SD"]
    csv_25sp = deterministic_process_compare("25SP", str(dir_25sp / "DSSBatch.v48"), var_names=proc_vars, run_dir=str(dir_25sp))
    csv_26sp = deterministic_process_compare("26SP", str(dir_26sp / "DSSBatch.v48"), var_names=proc_vars, run_dir=str(dir_26sp))
    csv_25fa = deterministic_process_compare("25FA", str(dir_25fa / "DSSBatch.v48"), var_names=proc_vars, run_dir=str(dir_25fa))

    df_25sp = pd.read_csv(csv_25sp).assign(season="25SP")
    df_26sp = pd.read_csv(csv_26sp).assign(season="26SP")
    df_25fa = pd.read_csv(csv_25fa).assign(season="25FA")

    df_all = pd.concat([df_25sp, df_26sp, df_25fa], ignore_index=True)
    print(f"Process compare row counts: 25SP={len(df_25sp)}, 26SP={len(df_26sp)}, 25FA={len(df_25fa)}, All={len(df_all)}")

    for sid, df_s in [("25SP", df_25sp), ("26SP", df_26sp), ("25FA", df_25fa), ("Overall", df_all)]:
        print(f"\n--- Process Metrics for {sid} ---")
        for v in ["LAID", "LWAD", "SWAD", "CHTD"]:
            sub = df_s[(df_s[f"OBS_{v}"] > 0) & np.isfinite(df_s[f"SIM_{v}"])]
            if len(sub) == 0:
                print(f"  {v}: No observations")
                continue
            rmse, nrmse, d, r2 = calc_metrics(sub[f"OBS_{v}"], sub[f"SIM_{v}"])
            o_m = sub[f"OBS_{v}"].mean()
            s_m = sub[f"SIM_{v}"].mean()
            bias = s_m - o_m
            print(f"  {v:5s}: N={len(sub):2d}, ObsMean={o_m:8.2f}, SimMean={s_m:8.2f}, Bias={bias:8.2f}, RMSE={rmse:8.2f}, NRMSE={nrmse:6.2f}%, d={d:6.4f}, R2={r2:6.4f}")

if __name__ == "__main__":
    main()
