#!/usr/bin/env python3
"""Fertigation depth grid: 5-50 cm × 22 treatments using full_gen98_v5 real46
genetic parameters.  For each depth, modify all N side-dress FDEP in the FileX,
run DSSAT, extract terminal CHFPW per treatment, compute N gradients."""
import os, re, shutil, subprocess, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "workspace/reports/fertigation_depth_grid"
GRID_ROOT = WORK / "runs"
DEPTHS = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]

# Template: the verified det_direct environment (has both TMX + DSSAT + all inputs)
TEMPLATE = ROOT / "workspace/reports/fullgen98v2_real70_22tmt_20260915/det_direct"
PARAMS = WORK / "real46_params.csv"
WN_MAP = pd.read_csv(WORK / "water_n_mapping.csv")

# Treatment mapping: RUN 1-10 = 25SP TN 2,3,4,5,9,10,11,12,13,14; RUN 11-22 = 26SP TN 1-12
TRT_25 = [2,3,4,5,9,10,11,12,13,14]
TRT_26 = list(range(1,13))
ALL_TRTS = TRT_25 + TRT_26
RUN_MAP = {tn: i+1 for i, tn in enumerate(ALL_TRTS)}


def modify_fdep(tmx_path: Path, depth: int) -> int:
    """Change all N side-dress (FE005, non-first per treatment) FDEP to depth."""
    lines = tmx_path.read_text(encoding="utf-8-sig").splitlines(keepends=True)
    section = None
    header = []
    changed = 0
    seen_base = set()
    for j, raw in enumerate(lines):
        line = raw.rstrip("\r\n")
        stripped = line.strip()
        if stripped.startswith("@"):
            section = stripped.split()[0][1:]
            header = stripped.split()
            seen_base = set()
            continue
        if section == "F" and "FDEP" in header:
            spans = [(m.start(), m.end()) for m in re.finditer(r"\S+", line)]
            fmcd_i = header.index("FMCD")  # data[j] ↔ header[j]
            fdep_i = header.index("FDEP")
            if len(spans) > fdep_i:
                trno = line[spans[0][0]:spans[0][1]].strip()
                fmcd = line[spans[fmcd_i][0]:spans[fmcd_i][1]]
                if fmcd == "FE005":
                    if trno in seen_base:
                        cur = line[spans[fdep_i][0]:spans[fdep_i][1]].strip()
                        new = str(depth)
                        if cur != new:
                            lines[j] = line[:spans[fdep_i][0]] + new.rjust(
                                spans[fdep_i][1] - spans[fdep_i][0]) + line[spans[fdep_i][1]:]
                            changed += 1
                    else:
                        seen_base.add(trno)
    tmx_path.write_text("".join(lines), encoding="utf-8", newline="")
    return changed


def read_terminal_chfpw(freshwt_path: Path) -> dict:
    """Read terminal CHFPW per RUN from FreshWt.OUT."""
    from src.dssat.run_dssat import _read_freshwt_var_by_run
    cf = _read_freshwt_var_by_run(str(freshwt_path), "CHFPW")
    result = {}
    for rn, dates in cf.items():
        if dates:
            last = sorted(dates.keys())[-1]
            result[rn] = dates[last]
    return result


def run_depth(depth: int) -> dict:
    """Run all 22 treatments at a given fertigation depth."""
    wdir = GRID_ROOT / f"depth_{depth:02d}"
    if wdir.exists():
        shutil.rmtree(wdir)
    shutil.copytree(TEMPLATE, wdir)

    # Modify FDEP in both TMX files
    n25 = modify_fdep(wdir / "XXQL2501.TMX", depth)
    n26 = modify_fdep(wdir / "XXQL2601.TMX", depth)

    # Inject real46 params into ECO (same approach as real70)
    p = pd.read_csv(PARAMS)
    params = dict(zip(p["name"].astype(str).str.lower(), pd.to_numeric(p["value"], errors="coerce")))
    eco_path = wdir / "TMGRO048.ECO"
    if eco_path.exists():
        elines = eco_path.read_text(encoding="utf-8-sig").splitlines(keepends=True)
        header = None
        for j, line in enumerate(elines):
            if line.strip().startswith("@ECO#"):
                header = line.split()
                header[0] = header[0].lstrip("@")
                continue
            if header and line.strip().startswith("TM0001"):
                spans = [(m.start(), m.end()) for m in re.finditer(r"\S+", line)]
                for k, hname in enumerate(header):
                    ln = hname.lower()
                    if ln in params and k < len(spans):
                        val = params[ln]
                        s, e = spans[k]
                        new_tok = "{:.6g}".format(val)
                        if len(new_tok) <= (e - s):
                            elines[j] = elines[j][:s] + new_tok.rjust(e - s) + elines[j][e:]
                        else:
                            elines[j] = elines[j][:s] + new_tok[:e-s] + elines[j][e:]
                break
        eco_path.write_text("".join(elines), encoding="utf-8", newline="")

    # Fix DSSATPRO
    dssatpro = wdir / "DSSATPRO.v48"
    if dssatpro.exists():
        tx = dssatpro.read_text(encoding="utf-8", errors="ignore")
        wpath = str(wdir)
        out = []
        for l in tx.splitlines(keepends=True):
            if l.strip().startswith("CRD ") or l.strip().startswith("TMD "):
                key = l.strip().split()[0]
                out.append(key + " " + wpath + "\n")
            else:
                out.append(l)
        dssatpro.write_text("".join(out), encoding="utf-8")

    # Run DSSAT
    env = dict(os.environ)
    r = subprocess.run([str(wdir/"DSCSM048.EXE"), "B", "DSSBatch.v48"],
        cwd=wdir, capture_output=True, text=True, env=env, timeout=300)
    if r.returncode != 0:
        return {"depth": depth, "error": f"DSSAT rc={r.returncode}"}

    # Extract terminal CHFPW
    terminals = read_terminal_chfpw(wdir / "FreshWt.OUT")

    # Map to treatment info
    results = []
    for tn in ALL_TRTS:
        rn = RUN_MAP[tn]
        y = terminals.get(rn, float("nan"))
        info = WN_MAP[WN_MAP["treatment"] == tn].iloc[0] if (WN_MAP["treatment"] == tn).any() else {}
        results.append({
            "depth_cm": depth, "treatment": tn, "run": rn,
            "season": info.get("season_id", ""), 
            "water": info.get("water_level", ""),
            "nitrogen": info.get("nitrogen_level", ""),
            "terminal_chfpw": y})
    return {"depth": depth, "n_fdep_changed": n25 + n26, "results": results,
            "rc": r.returncode}


def compute_gradients(df: pd.DataFrame) -> pd.DataFrame:
    """Compute N gradient response (N3-N0, N2-N0, N1-N0, range) per season×water×depth."""
    rows = []
    for (depth, season, water), g in df.groupby(["depth_cm", "season", "water"]):
        yn = {n: g[g["nitrogen"] == n]["terminal_chfpw"].mean()
              for n in ["N0", "N1", "N2", "N3"] if (g["nitrogen"] == n).any()}
        if "N0" in yn and "N3" in yn:
            vals = [v for v in yn.values() if pd.notna(v)]
            rows.append({
                "depth_cm": depth, "season": season, "water": water,
                "N0": yn.get("N0", np.nan), "N1": yn.get("N1", np.nan),
                "N2": yn.get("N2", np.nan), "N3": yn.get("N3", np.nan),
                "N3-N0": yn.get("N3", np.nan) - yn.get("N0", np.nan),
                "N2-N0": yn.get("N2", np.nan) - yn.get("N0", np.nan),
                "N1-N0": yn.get("N1", np.nan) - yn.get("N0", np.nan),
                "range": max(vals) - min(vals) if len(vals) > 1 else np.nan,
                "cv_pct": 100 * np.std(vals) / np.mean(vals) if len(vals) > 1 and np.mean(vals) > 0 else np.nan})
    return pd.DataFrame(rows)


def main():
    if GRID_ROOT.exists():
        shutil.rmtree(GRID_ROOT)
    GRID_ROOT.mkdir(parents=True)

    all_results = []
    for depth in DEPTHS:
        print(f"Running depth {depth} cm ...")
        r = run_depth(depth)
        if "error" in r:
            print(f"  FAILED: {r['error']}")
            continue
        all_results.extend(r["results"])
        print(f"  rc={r['rc']}, FDEP changed={r['n_fdep_changed']}")

    df = pd.DataFrame(all_results)
    df.to_csv(WORK / "all_treatment_yields.csv", index=False, encoding="utf-8-sig")

    grad = compute_gradients(df)
    grad.to_csv(WORK / "n_gradient_by_depth.csv", index=False, encoding="utf-8-sig")

    # Summary: which depth maximizes N3-N0 and range
    print("\n=== N gradient by depth (N3-N0, kg/ha) ===")
    pivot = grad.pivot_table(index="depth_cm", columns=["season", "water"],
                              values="N3-N0", aggfunc="first")
    print(pivot.round(0).to_string())
    print("\n=== Gradient range (max-min N, kg/ha) ===")
    pivot2 = grad.pivot_table(index="depth_cm", columns=["season", "water"],
                               values="range", aggfunc="first")
    print(pivot2.round(0).to_string())
    print("\n=== CV% across N levels ===")
    pivot3 = grad.pivot_table(index="depth_cm", columns=["season", "water"],
                               values="cv_pct", aggfunc="first")
    print(pivot3.round(2).to_string())

    # Best depth
    grad["abs_N3N0"] = grad["N3-N0"].abs()
    grad["abs_range"] = grad["range"].abs()
    best_n3n0 = grad.loc[grad["abs_N3N0"].idxmax()]
    best_range = grad.loc[grad["abs_range"].idxmax()]
    print(f"\nBest N3-N0 gradient: depth={best_n3n0['depth_cm']} cm, "
          f"{best_n3n0['season']}/{best_n3n0['water']}, N3-N0={best_n3n0['N3-N0']:.0f} kg/ha")
    print(f"Best range: depth={best_range['depth_cm']} cm, "
          f"{best_range['season']}/{best_range['water']}, range={best_range['range']:.0f} kg/ha")

    # Mean across all season×water combos
    mean_by_depth = grad.groupby("depth_cm")[["N3-N0", "N2-N0", "N1-N0", "range", "cv_pct"]].mean()
    print("\n=== Mean across all season×water ===")
    print(mean_by_depth.round(1).to_string())
    mean_by_depth.to_csv(WORK / "mean_gradient_by_depth.csv", encoding="utf-8-sig")


if __name__ == "__main__":
    main()
