"""Inspect N0 vs N3 Root Growth Dynamics, Root Depth, Layer Distribution, and Nitrogen Stress in DSSAT."""
import re
import sys
from pathlib import Path
import numpy as np
import pandas as pd

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
DET_DIR = ROOT / "workspace/runs/e02_v22_synergy_roots_official_200x6_20260821/deterministic_candidates/best_phi_member100_two_season_20260821"


def inspect_roots():
    for season in ["25SP", "26SP"]:
        sdir = DET_DIR / "_seasons" / season
        pg_file = sdir / "PlantGro.OUT"
        pn_file = sdir / "PlantN.OUT"
        
        n3_tn = 2
        n0_tn = 5 if season == "25SP" else 11
        
        # Read PlantGro
        pg_lines = pg_file.read_text(errors="ignore").splitlines()
        header = None
        cur_tn = None
        recs = []
        for l in pg_lines:
            if l.startswith("*RUN"):
                m = re.search(r"\*RUN\s+(\d+).*?XXQL\d+\s+(\d+)", l)
                if m:
                    cur_tn = int(m.group(2))
            elif l.startswith("@YEAR"):
                header = l.replace("@", "").split()
            elif cur_tn in [n3_tn, n0_tn] and header and l.strip() and not l.startswith("*") and not l.startswith("@"):
                parts = l.split()
                if len(parts) >= len(header) and parts[0].isdigit():
                    r = {header[i]: float(parts[i]) for i in range(len(header))}
                    r["TN"] = cur_tn
                    recs.append(r)
        df_pg = pd.DataFrame(recs)
        
        # Read PlantN
        pn_lines = pn_file.read_text(errors="ignore").splitlines()
        header_n = None
        cur_tn = None
        recs_n = []
        for l in pn_lines:
            if l.startswith("*RUN"):
                m = re.search(r"\*RUN\s+(\d+).*?XXQL\d+\s+(\d+)", l)
                if m:
                    cur_tn = int(m.group(2))
            elif l.startswith("@YEAR"):
                header_n = l.replace("@", "").split()
            elif cur_tn in [n3_tn, n0_tn] and header_n and l.strip() and not l.startswith("*") and not l.startswith("@"):
                parts = l.split()
                if len(parts) >= len(header_n) and parts[0].isdigit():
                    r = {header_n[i]: float(parts[i]) for i in range(len(header_n))}
                    r["TN"] = cur_tn
                    recs_n.append(r)
        df_pn = pd.DataFrame(recs_n)
        
        print(f"\n==========================================================================================")
        print(f"                       {season} Root Dynamics & Nitrogen Stress Inspection")
        print(f"==========================================================================================")
        
        for tn, label in [(n3_tn, "N3 (W3N3 充分水氮)"), (n0_tn, "N0 (W3N0 充分水零氮)")]:
            sub_pg = df_pg[df_pg["TN"] == tn]
            sub_pn = df_pn[df_pn["TN"] == tn]
            
            print(f"\n>>> Treatment TN {tn}: {label} <<<")
            daps = [20, 35, 50, 65, 80, 100]
            sub_dap = sub_pg[sub_pg["DAP"].isin(daps)].copy()
            
            cols = ["DAP", "LAID", "CWAD", "GWAD", "RWAD", "RDPD", "RLAD", "RL1D", "RL2D", "RL3D", "RL4D", "RL5D", "NSTD"]
            show_cols = [c for c in cols if c in sub_dap.columns]
            print(sub_dap[show_cols].to_string(index=False))
            
            last_pg = sub_pg.iloc[-1]
            last_pn = sub_pn.iloc[-1] if not sub_pn.empty else {}
            print(f"\n[Final Stage Summary - DAP {last_pg['DAP']:.0f}]")
            print(f"  Root Weight (RWAD): {last_pg.get('RWAD', -99):.1f} kg/ha  |  Total Dry Biomass (CWAD): {last_pg.get('CWAD', -99):.1f} kg/ha  |  Root/Total Ratio: {last_pg.get('RWAD', 0)/max(last_pg.get('CWAD', 1), 1)*100:.2f}%")
            print(f"  Root Depth (RDPD): {last_pg.get('RDPD', -99):.2f} m  |  Root Length Index (RLAD): {last_pg.get('RLAD', -99):.2f} cm2/cm2")
            
            rl_str = " | ".join([f"L{i} ({(i-1)*20}-{i*20}cm): {last_pg.get(f'RL{i}D', 0):.3f}" for i in range(1, 7)])
            print(f"  Layer Root Length Density (cm/cm3):\n    {rl_str}")
            
            if not sub_pn.empty:
                print(f"  Nitrogen Uptake (NUPC): {last_pn.get('NUPC', -99):.1f} kg N/ha  |  Root N Mass (RNAD): {last_pn.get('RNAD', -99):.1f} kg N/ha  |  Root N Concentration (RN%D): {last_pn.get('RN%D', -99):.2f}%")
                print(f"  Leaf N Concentration (LN%D): {last_pn.get('LN%D', -99):.2f}%  |  Stem N Concentration (SN%D): {last_pn.get('SN%D', -99):.2f}%")


if __name__ == "__main__":
    inspect_roots()
