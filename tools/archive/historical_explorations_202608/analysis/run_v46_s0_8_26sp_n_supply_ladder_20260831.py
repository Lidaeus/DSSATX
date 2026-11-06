"""Isolated 26SP nitrogen-supply ladder for mechanism identification.

The formal fertilizer schedule is copied to scratch and FAMN is multiplied
by a diagnostic factor in 26SP only.  This is not a calibration proposal:
the formal bundles and observations are never modified.  The aim is to test
whether lowering mineral-N supply can activate the dormant CROPGRO N-stress
channel before considering any genetic parameter release.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PARAMS = ROOT / "workspace/runs/e02_formal_v46_step20_custom26sp_20260831_200x4/best_member_71_deterministic_20260831/best_member_71_params.csv"
B25 = ROOT / "data/user/experiments/xxql2501_formal_scheme4_soil_20260830"
B26 = ROOT / "data/user/experiments/xxql2601_formal_scheme4_soil_20260830"
MAP = ROOT / "configs/runs/e02_mapping_25sp_w3w1_26sp_w2w1_n2n0_20260830.csv"
OUT = ROOT / "workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/s0_8_26sp_n_supply_ladder"


def _scale_famn(path: Path, factor: float) -> int:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    in_fert = False; changed = 0
    for i, raw in enumerate(lines):
        s = raw.strip()
        if s.upper().startswith("*FERTILIZERS"):
            in_fert = True; continue
        if in_fert and s.startswith("*"):
            in_fert = False
        if not in_fert or not re.match(r"^\s*\d+\s+\d{5}\s+", raw):
            continue
        spans = list(re.finditer(r"\S+", raw))
        if len(spans) < 6:
            continue
        # Token 5 is FAMN.  Preserve the original character span/spacing.
        sp = spans[5]
        try:
            old = float(sp.group())
        except ValueError:
            continue
        new = old * factor
        width = sp.end() - sp.start()
        text = f"{new:.3f}" if abs(new - round(new)) > 1e-9 else f"{int(round(new))}"
        if len(text) > width:
            text = f"{new:.2f}"[:width]
        text = text.rjust(width)
        lines[i] = raw[:sp.start()] + text + raw[sp.end():]
        changed += 1
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def _nse(o, s):
    o = pd.to_numeric(o, errors="coerce").to_numpy(float); s = pd.to_numeric(s, errors="coerce").to_numpy(float)
    ok = np.isfinite(o) & np.isfinite(s) & (o > -90) & (s > -90); o, s = o[ok], s[ok]
    den = float(np.square(o - o.mean()).sum())
    return float(1 - np.square(s - o).sum() / den) if len(o) and den > 0 else np.nan


def _max_nstress(path: Path) -> float:
    # PlantGro has one block per local run; parse the NSTD column only.
    maxv = 0.0; header = None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if raw.startswith("@YEAR"):
            header = raw.strip().split(); header[0] = "YEAR"; continue
        if header is None or not raw.strip() or not raw.split()[0].isdigit():
            continue
        f = raw.split()
        if len(f) < len(header) or "NSTD" not in header:
            continue
        try: maxv = max(maxv, abs(float(f[header.index("NSTD")])) )
        except ValueError: pass
    return maxv


def _evaluate(rd: Path) -> dict[str, object]:
    import src.reporting.analyze_results as ar
    meta = pd.read_csv(MAP)
    row: dict[str, object] = {}
    for season in ("25SP", "26SP"):
        sd = rd / "_seasons" / season; ar.WORKSPACE = str(sd)
        ar.deterministic_process_compare(season, str(sd / "DSSBatch.v48"), var_names=["LAID", "LWAD", "SWAD", "CHTD"], run_dir=str(sd))
        ar.deterministic_harvest_compare(season, str(sd / "DSSBatch.v48"), run_dir=str(sd))
        p = pd.read_csv(sd / f"{season}_deterministic_process_compare.csv")
        h = pd.read_csv(sd / f"{season}_deterministic_harvest_compare.csv")
        terminal = h.sort_values(["TN", "DATE", "HNO"]).groupby("TN", as_index=False).tail(1)
        first = h[h.HNO.eq(1)]
        row[f"{season}_first_fresh_sim_range"] = float(np.ptp(first.SIM_FRESH_CUM))
        row[f"{season}_first_fresh_obs_range"] = float(np.ptp(first.OBS_FRESH_CUM))
        row[f"{season}_terminal_fresh_rrmse_pct"] = float(100*np.sqrt(np.mean((terminal.SIM_FRESH_CUM-terminal.OBS_FRESH_CUM)**2))/np.mean(np.abs(terminal.OBS_FRESH_CUM)))
        row[f"{season}_fresh_cum_nse"] = _nse(h.OBS_FRESH_CUM, h.SIM_FRESH_CUM)
        row[f"{season}_lai_nse"] = _nse(p.OBS_LAID, p.SIM_LAID)
        m = meta[meta.season_id.eq(season)].set_index("treatment")
        t = terminal.merge(m[["water_level", "nitrogen_level"]], left_on="TN", right_index=True, how="left")
        e = []
        for _, g in t.groupby("water_level"):
            b = g.set_index("nitrogen_level")
            if "N0" not in b.index: continue
            for lev in ("N1", "N2", "N3"):
                if lev in b.index:
                    e.append(float((b.loc[lev,"SIM_FRESH_CUM"]-b.loc["N0","SIM_FRESH_CUM"]) - (b.loc[lev,"OBS_FRESH_CUM"]-b.loc["N0","OBS_FRESH_CUM"])))
        row[f"{season}_n_response_mae"] = float(np.mean(np.abs(e))) if e else np.nan
        row[f"{season}_max_nstd"] = _max_nstress(sd / "PlantGro.OUT")
    return row


def main() -> int:
    if OUT.exists(): shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    results = []
    for factor in (1.0, 0.5, 0.25, 0.10):
        case = f"famn_{factor:.2f}"; rd = OUT / case; rd.mkdir()
        b25, b26 = rd / "exp25", rd / "exp26"; shutil.copytree(B25, b25); shutil.copytree(B26, b26)
        changed = _scale_famn(next(b26.glob("*.TMX")), factor)
        design = {"schema_version":1,"design_id":case,"cultivar_identity":"TM0008","shared_parameter_scope":"best71_s0_8","bounds_id":"best71_deterministic","observation_policy":"configs/runs/e02_from_scratch_objective_contract_20260826.csv","group_policy":"configs/runs/e02_group_policy_v40_formal_fresh_3x_yield.csv","nitrogen_response_objective":{"enabled":False},"water_response_objective":{"enabled":False},"harvest_fresh_objective":{"enabled":False},"process_state_objective":{"enabled":False},"seasons":[{"season_id":"25SP","experiment_code":"XXQL2501","bundle_path":str(b25),"role":"calibration","treatments":[2,3,4,5,9,10,11,12,13,14]},{"season_id":"26SP","experiment_code":"XXQL2601","bundle_path":str(b26),"role":"calibration","treatments":list(range(1,13))}]}
        dp = rd / "joint_design.json"; dp.write_text(json.dumps(design, indent=2), encoding="utf-8")
        cmd = [sys.executable,str(ROOT/"src/calibration/run_multiseason.py"),"--design",str(dp),"--param-csv",str(PARAMS),"--prefix","s0_8","--harvest-var","CHFPW","--keep-nitrogen-outputs"]
        subprocess.run(cmd,cwd=rd,check=True,encoding="cp1252",errors="replace")
        row = {"case":case,"famn_factor":factor,"fertilizer_rows_changed":changed,**_evaluate(rd)}; results.append(row)
        pd.DataFrame(results).to_csv(OUT/"s0_8_scorecard.csv",index=False,encoding="utf-8-sig"); print(row,flush=True)
    (OUT/"s0_8_manifest.json").write_text(json.dumps({"anchor":str(PARAMS),"factors":[1.0,0.5,0.25,0.10],"formal_bundles_untouched":True},indent=2),encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
