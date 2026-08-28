"""Deterministic OAT screens for selected-eight water parameters and curves."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.reporting.analyze_results import deterministic_harvest_compare

CASE = "e02_selected8_fixedsoil_nse_official_200x6_20260818"
RUN_DIR = ROOT / "workspace" / "runs" / CASE
DESIGN = ROOT / "configs" / "runs" / "eggplant_e02_selected8_fixedsoil_nse_20260818.json"
BASE_PARAMS = RUN_DIR / "deterministic_candidates" / "best_phi_member192_three_season_20260818" / "best_member_192_params.csv"
OUT = ROOT / "workspace" / "reports" / "selected8_water_parameter_screen_20260818"
EXE = ROOT / "DSCSM048.EXE"
SPE = ROOT / "data" / "templates" / "genotype" / "TMGRO048.SPE.base"

SCALAR_PROFILES = {
    "DSWBAR": [7.0, 10.0, 13.76771175, 14.678, 17.5, 21.5, 25.39433325, 30.0],
    "RWUMX": [0.015, 0.020, 0.0254519075, 0.035, 0.042017, 0.0533926125, 0.075],
    "RTEXF": [0.050, 0.070, 0.08678809675, 0.091614, 0.130, 0.160, 0.19776084825, 0.250],
    "PORMIN": [0.001, 0.003, 0.005068776, 0.005241, 0.010, 0.020, 0.033071504, 0.050],
}
CURVE_DEFAULTS = {
    "SWFAC_REC": 1.0, "YSWFAC_MID": 1.0, "SWBAR_REC": 0.25,
    "YSWBAR_MID": 1.0, "TRFAC_XMID": 0.50, "YTRFAC_MAX": 0.0,
}
CURVE_LEVELS = {
    "SWFAC_REC": [0.35, 0.65, 1.0],
    "YSWFAC_MID": [0.30, 0.65, 1.0],
    "SWBAR_REC": [0.08, 0.40, 0.72],
    "YSWBAR_MID": [0.15, 0.55, 1.0],
    "TRFAC_XMID": [0.20, 0.45, 0.70],
    "YTRFAC_MAX": [0.0, 0.20, 0.45],
}
MAPPING = {
    "25SP": {"N3": (2, 10), "N0": (5, 13)},
    "26SP": {"N3": (2, 3), "N0": (11, 12)},
}
TREATMENTS = {"25SP": [2, 5, 10, 13], "26SP": [2, 11, 3, 12]}


def nse(observed: pd.Series, simulated: pd.Series) -> float:
    obs = pd.to_numeric(observed, errors="coerce").to_numpy(float)
    sim = pd.to_numeric(simulated, errors="coerce").to_numpy(float)
    valid = np.isfinite(obs) & np.isfinite(sim)
    obs, sim = obs[valid], sim[valid]
    sst = float(np.square(obs - obs.mean()).sum()) if len(obs) else 0.0
    return float(1.0 - np.square(sim - obs).sum() / sst) if sst > 0 else float("nan")


def _set_params(changes: dict[str, float], target: Path) -> None:
    frame = pd.read_csv(BASE_PARAMS)
    frame["name"] = frame["name"].astype(str).str.upper()
    for name, value in changes.items():
        mask = frame["name"].eq(name)
        if mask.any():
            frame.loc[mask, "value"] = float(value)
        else:
            frame.loc[len(frame)] = {"name": name, "value": float(value)}
    frame.to_csv(target, index=False)


def _score(case_dir: Path, case: str, label: str, changes: dict[str, float]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    season_tables: dict[str, pd.DataFrame] = {}
    for season in MAPPING:
        season_dir = case_dir / "_seasons" / season
        compare_path = season_dir / f"{season}_deterministic_harvest_compare.csv"
        if not compare_path.exists():
            filex = next(season_dir.glob("*.TMX"))
            batch = season_dir / "analysis_batch.v48"
            batch.write_text(
                "\n".join(
                    f"{filex.resolve()} {int(treatment)} 1 0 0 0"
                    for treatment in TREATMENTS[season]
                ) + "\n",
                encoding="utf-8",
            )
            deterministic_harvest_compare(
                season, str(batch), run_dir=str(season_dir)
            )
        table = pd.read_csv(compare_path)
        season_tables[season] = table
        terminal = table.loc[table["HNO"].eq(table.groupby("TN")["HNO"].transform("max"))]
        rows.append({
            "case": case, "label": label, **changes, "metric": "DRY_CUM_NSE",
            "season": season, "nitrogen_level": "ALL", "value": nse(table["OBS_DRY_CUM"], table["SIM_DRY_CUM"]),
        })
        rows.append({
            "case": case, "label": label, **changes, "metric": "TERMINAL_DRY_PBIAS_PCT",
            "season": season, "nitrogen_level": "ALL",
            "value": float(100.0 * (terminal["SIM_DRY_CUM"].sum() - terminal["OBS_DRY_CUM"].sum()) / terminal["OBS_DRY_CUM"].sum()),
        })
        for nitrogen, (high_tn, low_tn) in MAPPING[season].items():
            high = table.loc[table["TN"].eq(high_tn), ["HNO", "DATE", "OBS_DRY_CUM", "SIM_DRY_CUM"]]
            low = table.loc[table["TN"].eq(low_tn), ["HNO", "DATE", "OBS_DRY_CUM", "SIM_DRY_CUM"]]
            pair = high.merge(low, on=["HNO", "DATE"], suffixes=("_high", "_low"), validate="one_to_one")
            obs = pair["OBS_DRY_CUM_high"] - pair["OBS_DRY_CUM_low"]
            sim = pair["SIM_DRY_CUM_high"] - pair["SIM_DRY_CUM_low"]
            rows.append({
                "case": case, "label": label, **changes, "metric": "W_RESPONSE_NSE",
                "season": season, "nitrogen_level": nitrogen, "value": nse(obs, sim),
            })
    return rows


def _run(label: str, changes: dict[str, float], out: Path) -> list[dict[str, object]]:
    slug = "_".join(f"{name.lower()}_{value:.6g}" for name, value in changes.items()) or "baseline"
    case = f"water_screen_{label}_{slug}".replace(".", "p")
    case_dir = out / case
    metrics_file = case_dir / "screen_metrics.json"
    if metrics_file.exists():
        return json.loads(metrics_file.read_text(encoding="utf-8"))
    case_dir.mkdir(parents=True, exist_ok=True)
    params = case_dir / "parameters.csv"
    _set_params(changes, params)
    env = os.environ.copy()
    env["DSSAT_CUSTOM_EXE"] = str(EXE.resolve())
    env["DSSAT_SPE_BASE"] = str(SPE.resolve())
    command = [
        sys.executable, str(ROOT / "src" / "calibration" / "run_multiseason.py"),
        "--design", str(DESIGN), "--param-csv", str(params), "--prefix", case,
        "--harvest-var", "CHPDT", "--keep-nitrogen-outputs",
    ]
    subprocess.run(command, cwd=case_dir, env=env, check=True)
    rows = _score(case_dir, case, label, changes)
    metrics_file.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["scalar", "curves", "all"], default="all")
    parser.add_argument("--out-dir", type=Path, default=OUT)
    args = parser.parse_args()
    out = args.out_dir.resolve(); out.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict[str, object]] = []
    all_rows.extend(_run("baseline", {}, out))
    if args.phase in {"scalar", "all"}:
        for parameter, values in SCALAR_PROFILES.items():
            for value in values:
                all_rows.extend(_run(f"scalar_{parameter.lower()}", {parameter: value}, out))
    if args.phase in {"curves", "all"}:
        for parameter, values in CURVE_LEVELS.items():
            for value in values:
                changes = dict(CURVE_DEFAULTS); changes[parameter] = value
                all_rows.extend(_run(f"curve_{parameter.lower()}", changes, out))
    result = pd.DataFrame(all_rows).drop_duplicates(["case", "metric", "season", "nitrogen_level"])
    result.to_csv(out / "water_parameter_screen_metrics.csv", index=False, encoding="utf-8-sig")
    manifest = {
        "base_member": "192", "base_case": CASE, "design": str(DESIGN),
        "scalar_profiles": SCALAR_PROFILES, "curve_defaults": CURVE_DEFAULTS,
        "curve_levels": CURVE_LEVELS,
        "advancement_gate": {
            "dry_cumulative_nse": "no season may decline by more than 0.03 absolute versus baseline",
            "yield_scale": "absolute terminal dry PBIAS may not worsen by more than 5 percentage points",
            "bound_widening": "only if a gate-qualified profile improves mean season x N W_RESPONSE NSE and the optimum remains on an outer tested value",
        },
    }
    (out / "screen_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
