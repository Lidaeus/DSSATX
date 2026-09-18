#!/usr/bin/env python3
"""Audit initial soil mineral nitrogen (SNO3, SNH4, Total inorganic N) for all treatments
in 25SP and 26SP, and evaluate whether initial nitrogen causes yield inversion.
"""

from __future__ import annotations

import re
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_tmx_ic(tmx_path: Path):
    text = tmx_path.read_text(encoding="utf-8", errors="ignore")
    
    # 1. Parse treatments table
    tmts_match = re.search(r"\*TREATMENTS.*?\n(.*?)(?:\n\*[A-Z]|\Z)", text, re.DOTALL)
    tmts_data = {}
    if tmts_match:
        for line in tmts_match.group(1).splitlines():
            if line.strip() and not line.startswith("@"):
                parts = line.split()
                if len(parts) >= 13:
                    try:
                        tn = int(parts[0])
                        ic_lvl = int(parts[-10])
                        tmts_data[tn] = ic_lvl
                    except:
                        pass
                    
    # 2. Parse IC blocks
    ic_match = re.search(r"\*INITIAL CONDITIONS.*?\n(.*?)(?:\n\*[A-Z]|\Z)", text, re.DOTALL)
    ic_data = {}
    if ic_match:
        current_ic = None
        for line in ic_match.group(1).splitlines():
            if line.startswith("@C") and "PCR" in line:
                continue
            elif line.startswith("@C") and "ICBL" in line:
                continue
            elif line.strip().startswith("*"):
                break
            
            parts = line.split()
            if not parts:
                continue
            
            if len(parts) >= 10:
                try:
                    current_ic = int(parts[0])
                except:
                    pass
            elif len(parts) >= 4 and current_ic is not None:
                floats = re.findall(r"[-+]?(?:\d*\.\d+|\d+)", line)
                if len(floats) >= 5:
                    c = int(floats[0])
                    icbl = float(floats[1])
                    sh2o = float(floats[2])
                    snh4 = float(floats[3])
                    sno3 = float(floats[4])
                    ic_data.setdefault(c, []).append({
                        "icbl": icbl, "sh2o": sh2o, "snh4": snh4, "sno3": sno3
                    })
                    
    return tmts_data, ic_data


def summarize_season(season_id: str, tmx_file: Path, mapping: pd.DataFrame) -> pd.DataFrame:
    tmts_dict, ic_dict = parse_tmx_ic(tmx_file)
    m_sub = mapping[mapping["season_id"] == season_id].set_index("treatment")
    records = []
    for tn in sorted(tmts_dict.keys()):
        ic_lvl = tmts_dict[tn]
        layers = ic_dict.get(ic_lvl, [])
        prev_d = 0.0
        tot_no3_kg = 0.0
        tot_nh4_kg = 0.0
        sno3_profile = []
        snh4_profile = []
        for l in layers:
            thick = l["icbl"] - prev_d
            prev_d = l["icbl"]
            bd = 1.45
            tot_no3_kg += l["sno3"] * bd * thick * 0.1
            tot_nh4_kg += l["snh4"] * bd * thick * 0.1
            sno3_profile.append(f"{l['icbl']:.0f}cm:{l['sno3']:.1f}")
            snh4_profile.append(f"{l['icbl']:.0f}cm:{l['snh4']:.1f}")
            
        w = m_sub.loc[tn, "water_level"] if tn in m_sub.index else "?"
        n = m_sub.loc[tn, "nitrogen_level"] if tn in m_sub.index else "?"
        n_kg = m_sub.loc[tn, "nitrogen_kg_ha"] if tn in m_sub.index else np.nan
        role = m_sub.loc[tn, "objective_role"] if tn in m_sub.index else "?"
        records.append({
            "TN": tn, "Water": w, "N_Level": n, "Fert_N_kg": n_kg, "Role": role,
            "Init_SNO3_kg_ha": round(tot_no3_kg, 1),
            "Init_SNH4_kg_ha": round(tot_nh4_kg, 1),
            "Total_Init_MinN": round(tot_no3_kg + tot_nh4_kg, 1),
            "Total_N_Supply": round(tot_no3_kg + tot_nh4_kg + float(n_kg), 1) if pd.notna(n_kg) else np.nan,
            "SNO3_profile": " | ".join(sno3_profile),
            "SNH4_profile": " | ".join(snh4_profile),
        })
    return pd.DataFrame(records)


def main():
    mapping = pd.read_csv(PROJECT_ROOT / "configs/runs/e02_mapping_26sp_w2_w1_20260830.csv")
    f25 = PROJECT_ROOT / "data/user/experiments/xxql2501_formal_scheme4_soil_20260830/XXQL2501.TMX"
    f26 = PROJECT_ROOT / "data/user/experiments/xxql2601_formal_scheme4_soil_20260830/XXQL2601.TMX"
    
    df25 = summarize_season("25SP", f25, mapping)
    df26 = summarize_season("26SP", f26, mapping)
    
    print("========================== 25SP INITIAL SOIL NITROGEN AUDIT ==========================")
    print(df25[["TN", "Water", "N_Level", "Fert_N_kg", "Role", "Init_SNO3_kg_ha", "Init_SNH4_kg_ha", "Total_Init_MinN", "Total_N_Supply"]].to_string(index=False))
    
    print("\n========================== 26SP INITIAL SOIL NITROGEN AUDIT ==========================")
    print(df26[["TN", "Water", "N_Level", "Fert_N_kg", "Role", "Init_SNO3_kg_ha", "Init_SNH4_kg_ha", "Total_Init_MinN", "Total_N_Supply"]].to_string(index=False))
    
    out_dir = PROJECT_ROOT / "workspace/reports/initial_soil_nitrogen_audit_20260830"
    out_dir.mkdir(parents=True, exist_ok=True)
    df25.to_csv(out_dir / "25SP_initial_nitrogen_audit.csv", index=False)
    df26.to_csv(out_dir / "26SP_initial_nitrogen_audit.csv", index=False)
    print(f"\nSaved audit CSVs to {out_dir}")


if __name__ == "__main__":
    main()
