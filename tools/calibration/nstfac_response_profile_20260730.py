"""Deterministic NSTFAC profile for the v4 spring-pair best member."""
from __future__ import annotations
import argparse, json, re, subprocess, sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "configs/runs/eggplant_e02_spring_pair_histbest_v1_20260730.json"
BASE_PARAMS = ROOT / "workspace/diagnostics/e02_spring_pair_histbest_4corner_150x5_20260730_v4_best/best_member_74_parameters.csv"
MAPPING = {"25SP": {13: ("W1", "N0"), 10: ("W1", "N3"), 5: ("W3", "N0"), 2: ("W3", "N3")}, "26SP": {12: ("W1", "N0"), 3: ("W1", "N3"), 9: ("W3", "N0"), 1: ("W3", "N3")}}

def harvest(path: Path) -> pd.DataFrame:
    rows = []
    pat = re.compile(r"RUN\s+(\d+)\s+TN\s+(\d+)\s+HNO\s+(\d+)\s+DATE\s+(\d+).*?@CHPDTS@\s+([-+0-9.eE]+)")
    for line in path.read_text(encoding="utf-8").splitlines():
        m = pat.search(line)
        if m:
            rows.append({"global_run": int(m.group(1)), "treatment": int(m.group(2)), "hno": int(m.group(3)), "date": int(m.group(4)), "chpdt": float(m.group(5))})
    return pd.DataFrame(rows)

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=ROOT / "workspace/diagnostics/nstfac_response_profile_20260730")
    args = ap.parse_args()
    out = args.out_dir.resolve(); out.mkdir(parents=True, exist_ok=True)
    base = pd.read_csv(BASE_PARAMS)
    values = np.linspace(0.2, 1.0, 10)
    all_rows = []
    for i, value in enumerate(values, 1):
        case = f"nstfac_{i:02d}_{value:.6f}"
        case_dir = out / case; case_dir.mkdir(parents=True, exist_ok=True)
        params = base.copy(); params.loc[params["name"].eq("NSTFAC"), "value"] = float(value)
        param_path = case_dir / "parameters.csv"; params.to_csv(param_path, index=False)
        subprocess.run([sys.executable, str(ROOT / "src/calibration/run_multiseason.py"), "--design", str(DESIGN), "--param-csv", str(param_path), "--prefix", case, "--harvest-var", "CHPDT", "--keep-nitrogen-outputs"], cwd=case_dir, check=True)
        mapping = pd.read_csv(case_dir / f"{case}_run_mapping.csv")
        h = harvest(case_dir / "PestHarvest.OUT").merge(mapping[["global_run", "season_id"]], on="global_run", how="left")
        h = h[h["hno"] == h.groupby(["global_run"])["hno"].transform("max")].copy()
        for season, tr in MAPPING.items():
            for water in ("W1", "W3"):
                cells = {(tn, n): h.loc[(h.season_id.eq(season)) & (h.treatment.eq(tn)), "chpdt"].iloc[-1] for tn, (w, n) in tr.items() if w == water and not h.loc[(h.season_id.eq(season)) & (h.treatment.eq(tn)), "chpdt"].empty}
                if (next((tn for tn, pair in tr.items() if pair == (water, "N0")), None), "N0") in cells and (next((tn for tn, pair in tr.items() if pair == (water, "N3")), None), "N3") in cells:
                    n0 = cells[(next(tn for tn, pair in tr.items() if pair == (water, "N0")), "N0")]
                    n3 = cells[(next(tn for tn, pair in tr.items() if pair == (water, "N3")), "N3")]
                    all_rows.append({"nstfac": float(value), "profile_index": i, "season": season, "water": water, "N0_chpdt": n0, "N3_chpdt": n3, "N3_minus_N0": n3 - n0, "N3_logratio_N0": np.log1p(n3) - np.log1p(n0)})
    result = pd.DataFrame(all_rows)
    result.to_csv(out / "nstfac_n_response_profile.csv", index=False)
    summary = result.groupby(["nstfac", "season", "water"], as_index=False)[["N3_minus_N0", "N3_logratio_N0"]].first()
    summary.to_csv(out / "nstfac_n_response_summary.csv", index=False)
    (out / "profile_manifest.json").write_text(json.dumps({"base_parameters": str(BASE_PARAMS), "design": str(DESIGN), "nstfac_values": values.tolist(), "status": "completed"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(result.to_string(index=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
