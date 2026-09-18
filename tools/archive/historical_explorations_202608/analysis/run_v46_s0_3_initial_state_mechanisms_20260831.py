"""Run the deterministic S0-3 mechanism controls for v46 best71.

The controls are deliberately counterfactual and isolated from the formal
bundles.  They test (B) a common initial planting state (PLWT/PAGE) and (C)
the timing of pre-first-harvest fertilizer applications.  No parameters,
observations, or frozen bundles are changed.
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
OUT = ROOT / "workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/s0_3_initial_state_mechanisms"


def _date_add(yyddd: int, days: int) -> int:
    import datetime as dt
    yy, doy = divmod(int(yyddd), 1000)
    year = 2000 + yy if yy < 70 else 1900 + yy
    d = dt.date(year, 1, 1) + dt.timedelta(days=doy - 1 + int(days))
    return (d.year % 100) * 1000 + int(d.strftime("%j"))


def _edit_tmx(path: Path, season: str, plwt: float | None, page: float | None, fert_shift: int) -> dict[str, int]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    in_fert = False
    plant_changed = fert_changed = 0
    pdate = "25075" if season == "25SP" else "26075"
    for i, raw in enumerate(lines):
        s = raw.strip()
        if s.upper().startswith("*FERTILIZERS"):
            in_fert = True
            continue
        if in_fert and s.startswith("*"):
            in_fert = False
        if (plwt is not None or page is not None) and raw.lstrip().startswith("2 ") and pdate in raw and len(raw) >= 70:
            # PLWT/PAGE occupy fixed six-character columns (58:64/64:70).
            # Keep every other column and all spacing byte-for-byte stable.
            repl = raw
            if plwt is not None:
                repl = repl[:58] + f"{plwt:6.1f}" + repl[64:]
            if page is not None:
                repl = repl[:64] + f"{page:6.1f}" + repl[70:]
            lines[i] = repl
            plant_changed += 1
        if in_fert and fert_shift and re.match(r"^\s*\d+\s+\d{5}\s+", raw):
            f = raw.split()
            old = int(f[1])
            # Only move applications before the first observed harvest; the
            # ±3-day shift keeps 25SP (25140) and 26SP (26146) pre-harvest.
            cutoff = 25140 if season == "25SP" else 26146
            start = 25075 if season == "25SP" else 26075
            if start <= old < cutoff:
                f[1] = str(_date_add(old, fert_shift))
                lines[i] = raw[:3] + f"{_date_add(old, fert_shift):05d}" + raw[8:]
                fert_changed += 1
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"planting_rows_changed": plant_changed, "fertilizer_rows_shifted": fert_changed}


def _design(run_dir: Path, b25: Path, b26: Path, case: str) -> Path:
    d = {
        "schema_version": 1, "design_id": case, "cultivar_identity": "TM0008",
        "shared_parameter_scope": "best71_s0_3", "bounds_id": "best71_deterministic",
        "observation_policy": "configs/runs/e02_from_scratch_objective_contract_20260826.csv",
        "group_policy": "configs/runs/e02_group_policy_v40_formal_fresh_3x_yield.csv",
        "nitrogen_response_objective": {"enabled": False}, "water_response_objective": {"enabled": False},
        "harvest_fresh_objective": {"enabled": False}, "process_state_objective": {"enabled": False},
        "seasons": [
            {"season_id": "25SP", "experiment_code": "XXQL2501", "bundle_path": str(b25), "role": "calibration", "treatments": [2,3,4,5,9,10,11,12,13,14]},
            {"season_id": "26SP", "experiment_code": "XXQL2601", "bundle_path": str(b26), "role": "calibration", "treatments": list(range(1,13))},
        ],
    }
    p = run_dir / "joint_design.json"
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")
    return p


def _metric(o: pd.Series, s: pd.Series) -> float:
    o = pd.to_numeric(o, errors="coerce").to_numpy(float); s = pd.to_numeric(s, errors="coerce").to_numpy(float)
    ok = np.isfinite(o) & np.isfinite(s) & (o > -90) & (s > -90)
    o, s = o[ok], s[ok]
    if len(o) == 0: return float("nan")
    den = float(np.square(o - o.mean()).sum())
    return float(1 - np.square(s-o).sum()/den) if den > 0 else float("nan")


def run_case(case: str, plwt: float | None = None, page: float | None = None, fert_shift: int = 0) -> dict[str, object]:
    rd = OUT / case
    if rd.exists(): shutil.rmtree(rd)
    rd.mkdir(parents=True)
    b25, b26 = rd / "exp25", rd / "exp26"
    shutil.copytree(B25, b25); shutil.copytree(B26, b26)
    edits = {"25SP": _edit_tmx(next(b25.glob("*.TMX")), "25SP", plwt, page, fert_shift),
             "26SP": _edit_tmx(next(b26.glob("*.TMX")), "26SP", plwt, page, fert_shift)}
    design = _design(rd, b25, b26, case)
    cmd = [sys.executable, str(ROOT / "src/calibration/run_multiseason.py"), "--design", str(design), "--param-csv", str(PARAMS), "--prefix", "s0", "--harvest-var", "CHFPW", "--keep-nitrogen-outputs"]
    try:
        subprocess.run(cmd, cwd=rd, check=True, capture_output=True, text=True,
                       encoding="cp1252", errors="replace")
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"{case} failed: {(exc.stderr or exc.stdout or '')[-1200:]}") from exc
    import src.reporting.analyze_results as ar
    # The comparison helpers resolve relative FileX names through their
    # module-level WORKSPACE; point it at this isolated season directory.
    rows: dict[str, object] = {"case": case, "plwt": plwt, "page": page, "fert_shift_days": fert_shift, "edits": json.dumps(edits)}
    mapping = pd.read_csv(rd / "s0_run_mapping.csv")
    # Generate canonical deterministic comparison tables for later reuse.
    for season, b in (("25SP", b25), ("26SP", b26)):
        sd = rd / "_seasons" / season
        ar.WORKSPACE = str(sd)
        ar.deterministic_process_compare(season, str(sd / "DSSBatch.v48"), var_names=["LAID", "LWAD", "SWAD", "CHTD"], run_dir=str(sd))
        ar.deterministic_harvest_compare(season, str(sd / "DSSBatch.v48"), run_dir=str(sd))
        p = pd.read_csv(sd / f"{season}_deterministic_process_compare.csv")
        h = pd.read_csv(sd / f"{season}_deterministic_harvest_compare.csv")
        early = p[p["DATE"].eq(26122)] if season == "26SP" else pd.DataFrame()
        first = h[h["HNO"].eq(1)]
        terminal = h.sort_values(["TN", "DATE", "HNO"]).groupby("TN", as_index=False).tail(1)
        rows[f"{season}_early_lai_range"] = float(np.ptp(early["SIM_LAID"])) if len(early) else None
        rows[f"{season}_early_lai_obs_range"] = float(np.ptp(early["OBS_LAID"])) if len(early) else None
        rows[f"{season}_first_fresh_range"] = float(np.ptp(first["SIM_FRESH_CUM"])) if len(first) else None
        rows[f"{season}_first_fresh_obs_range"] = float(np.ptp(first["OBS_FRESH_CUM"])) if len(first) else None
        rows[f"{season}_terminal_fresh_rrmse_pct"] = float(100*np.sqrt(np.mean((terminal.SIM_FRESH_CUM-terminal.OBS_FRESH_CUM)**2))/np.mean(np.abs(terminal.OBS_FRESH_CUM)))
        rows[f"{season}_fresh_cum_nse"] = _metric(h["OBS_FRESH_CUM"], h["SIM_FRESH_CUM"])
        rows[f"{season}_lai_nse"] = _metric(p["OBS_LAID"], p["SIM_LAID"])
        # Terminal N contrasts are reported for all available same-water
        # strata.  They are descriptive here; no S0 case is promoted on
        # these values alone.
        meta = pd.read_csv(MAP)
        meta = meta[meta["season_id"].eq(season)].set_index("treatment")
        term = terminal.merge(meta[["water_level", "nitrogen_level"]], left_on="TN", right_index=True, how="left")
        rec = []
        for water, g in term.groupby("water_level"):
            byn = g.set_index("nitrogen_level")
            if "N0" not in byn.index: continue
            for lev in ("N1", "N2", "N3"):
                if lev in byn.index:
                    rec.append({"water": water, "level": lev,
                                "obs": float(byn.loc[lev, "OBS_FRESH_CUM"] - byn.loc["N0", "OBS_FRESH_CUM"]),
                                "sim": float(byn.loc[lev, "SIM_FRESH_CUM"] - byn.loc["N0", "SIM_FRESH_CUM"])})
        if rec:
            nr = pd.DataFrame(rec)
            rows[f"{season}_n_response_mae"] = float(np.mean(np.abs(nr.sim - nr.obs)))
            rows[f"{season}_n3_minus_n0_mean_sim"] = float(nr.loc[nr.level.eq("N3"), "sim"].mean()) if (nr.level.eq("N3").any()) else None
            rows[f"{season}_n2_minus_n0_mean_sim"] = float(nr.loc[nr.level.eq("N2"), "sim"].mean()) if (nr.level.eq("N2").any()) else None
            rows[f"{season}_n1_minus_n0_mean_sim"] = float(nr.loc[nr.level.eq("N1"), "sim"].mean()) if (nr.level.eq("N1").any()) else None
    return rows


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    cases = [("S0_3A_baseline", None, None, 0), ("S0_3B_plwt5", 5.0, None, 0), ("S0_3B_plwt12", 12.0, None, 0), ("S0_3B_page12", None, 12.0, 0), ("S0_3B_page60", None, 60.0, 0), ("S0_3B_plwt12_page12", 12.0, 12.0, 0), ("S0_3C_fert_minus3d", None, None, -3), ("S0_3C_fert_plus3d", None, None, 3)]
    out = []
    for c, w, p, sh in cases:
        print(f"[S0-3] running {c}", flush=True)
        out.append(run_case(c, w, p, sh))
    pd.DataFrame(out).to_csv(OUT / "s0_3_scorecard.csv", index=False, encoding="utf-8-sig")
    (OUT / "s0_3_manifest.json").write_text(json.dumps({"anchor": str(PARAMS), "bundle_25": str(B25), "bundle_26": str(B26), "cases": [x[0] for x in cases]}, indent=2), encoding="utf-8")
    print(pd.DataFrame(out).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
