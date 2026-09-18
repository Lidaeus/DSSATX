"""Analyze Soil Nitrogen Leaching and Solute Transport Dynamics under Irrigation in N0 treatments.

Examines:
1. Nitrate (NO3) and Ammonium (NH4) depth profile evolution over time (DAP 0 to harvest).
2. Root growth depth (RDPD) vs Nitrate concentration peak depth (layer-by-layer matching).
3. Irrigation events (dates, mm) and downward displacement of nitrate plumes.
4. Nitrogen mass balance in N0 (mineralization NMNC, leaching NLCC, plant uptake NUCM/NUPC, residual NIAD).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
import numpy as np
import pandas as pd

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
DET_DIR = ROOT / "workspace/runs/e02_v22_synergy_roots_official_200x6_20260821/deterministic_candidates/best_phi_member100_two_season_20260821"


def analyze_season_solute_transport(season: str):
    sdir = DET_DIR / "_seasons" / season
    sni_file = sdir / "SoilNi.OUT"
    pg_file = sdir / "PlantGro.OUT"
    pn_file = sdir / "PlantN.OUT"
    
    n3_tn = 2
    n0_tn = 5 if season == "25SP" else 11
    
    # 1. Parse SoilNi.OUT
    lines = sni_file.read_text(errors="ignore").splitlines()
    header, cur_tn, records = None, None, []
    for l in lines:
        if l.startswith("*RUN"):
            m = re.search(r"\*RUN\s+(\d+).*?XXQL\d+\s+(\d+)", l)
            if m: cur_tn = int(m.group(2))
        elif l.startswith("@YEAR"):
            header = l.replace("@", "").split()
        elif cur_tn in [n3_tn, n0_tn] and header and l.strip() and not l.startswith("*") and not l.startswith("@"):
            parts = l.split()
            if len(parts) >= len(header) and parts[0].isdigit():
                r = {header[i]: float(parts[i]) for i in range(len(header))}
                r["TN"] = cur_tn
                records.append(r)
    df_sni = pd.DataFrame(records)
    
    # 2. Parse PlantGro.OUT
    pg_lines = pg_file.read_text(errors="ignore").splitlines()
    header_pg, cur_tn, pg_records = None, None, []
    for l in pg_lines:
        if l.startswith("*RUN"):
            m = re.search(r"\*RUN\s+(\d+).*?XXQL\d+\s+(\d+)", l)
            if m: cur_tn = int(m.group(2))
        elif l.startswith("@YEAR"):
            header_pg = l.replace("@", "").split()
        elif cur_tn in [n3_tn, n0_tn] and header_pg and l.strip() and not l.startswith("*") and not l.startswith("@"):
            parts = l.split()
            if len(parts) >= len(header_pg) and parts[0].isdigit():
                r = {header_pg[i]: float(parts[i]) for i in range(len(header_pg))}
                r["TN"] = cur_tn
                pg_records.append(r)
    df_pg = pd.DataFrame(pg_records)
    
    print(f"\n==========================================================================================")
    print(f"       {season} Soil Nitrogen Transport & Leaching Analysis under Irrigation")
    print(f"==========================================================================================")
    
    for tn, label in [(n0_tn, f"N0 (TN {n0_tn} 零氮处理)"), (n3_tn, f"N3 (TN {n3_tn} 充分氮处理)")]:
        sub_sni = df_sni[df_sni["TN"] == tn].copy()
        sub_pg = df_pg[df_pg["TN"] == tn].copy()
        
        merged = pd.merge(sub_sni, sub_pg[["DAP", "RDPD", "RWAD", "RLAD", "LAID", "CWAD"]], left_on="DAS", right_on="DAP", how="left")
        
        print(f"\n>>> Treatment: {label} <<<")
        
        # Check milestones across season
        daps_check = [0, 10, 20, 35, 50, 65, 80, 100, 120]
        sub_show = merged[merged["DAS"].isin(daps_check)].copy()
        
        # Format nitrate by layers (ppm)
        # NI1D: 0-5cm, NI2D: 5-15cm, NI3D: 15-20cm, NI4D: 20-30cm, NI5D: 30-40cm, NI6D: 40-50cm, NI7D: 50-60cm, NI8D: 60-70cm, NI9D: 70-80cm, NI10: 80-180cm
        print(f"{'DAP':4s} | {'RootDep':7s} | {'Top NO3':8s} | {'Sub NO3':8s} | {'Deep NO3':8s} | {'Total N':8s} | {'Min N':7s} | {'Uptk N':7s} | {'Leach N':7s} | {'Soil NO3 Profile (0-5, 5-15, 15-30, 30-50, 50-80, 80-180cm)'}")
        print("-" * 110)
        
        for _, row in sub_show.iterrows():
            dap = int(row["DAS"])
            rdpd = f"{row.get('RDPD', 0):.2f}m" if pd.notna(row.get('RDPD')) else "0.00m"
            
            top_no3 = (row.get("NI1D", 0)*5 + row.get("NI2D", 0)*10 + row.get("NI3D", 0)*5 + row.get("NI4D", 0)*10) / 30.0 # 0-30cm avg
            sub_no3 = (row.get("NI5D", 0)*10 + row.get("NI6D", 0)*10 + row.get("NI7D", 0)*10) / 30.0 # 30-60cm avg
            deep_no3 = (row.get("NI8D", 0)*10 + row.get("NI9D", 0)*10 + row.get("NI10", 0)*100) / 120.0 # 60-180cm avg
            
            niad = f"{row.get('NIAD', 0):.1f}"
            nmnc = f"{row.get('NMNC', 0):.1f}"
            nucm = f"{row.get('NUCM', 0):.1f}"
            nlcc = f"{row.get('NLCC', 0):.1f}"
            
            # Layer profile string
            l_str = f"{row.get('NI1D',0):.1f}, {row.get('NI2D',0):.1f}, {row.get('NI4D',0):.1f}, {row.get('NI6D',0):.1f}, {row.get('NI8D',0):.1f}, {row.get('NI10',0):.1f}"
            
            print(f"{dap:4d} | {rdpd:7s} | {top_no3:7.1f}p | {sub_no3:7.1f}p | {deep_no3:7.1f}p | {niad:7s}k | {nmnc:6s}k | {nucm:6s}k | {nlcc:6s}k | [{l_str}]")
            
        last_row = merged.iloc[-1]
        print(f"\n[Final Soil Nitrogen Balance (kg N/ha)]")
        print(f"  Initial Soil Inorganic N: {merged.iloc[0].get('NIAD', 0):.1f} kg/ha")
        print(f"  + Cumulative Mineralization (NMNC): {last_row.get('NMNC', 0):.1f} kg/ha")
        print(f"  - Cumulative Root Uptake (NUCM): {last_row.get('NUCM', 0):.1f} kg/ha")
        print(f"  - Cumulative Leaching below 180cm (NLCC): {last_row.get('NLCC', 0):.1f} kg/ha")
        print(f"  = Final Residual Soil Inorganic N (NIAD): {last_row.get('NIAD', 0):.1f} kg/ha (Discrepancy: {last_row.get('TDNC', 0):.1f} kg/ha)")


def main():
    for s in ["25SP", "26SP"]:
        analyze_season_solute_transport(s)


if __name__ == "__main__":
    main()
