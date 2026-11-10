#!/usr/bin/env python3
"""run_s3_s4.py -- batch diagnostic figures for the S1/S3/S4 variant
replays using tools/diagnostics/diagnostics.py (Python diagnostic track).

Groups (selected 2026-11-09):
  yield4  fresh-yield nitrogen response, 4 variants (+observed via the
          fixtures comparison table when the date checks pass)
  psi     daily psi family (S3 NDecision; S4 NStatePsi)
  root    per-layer RootNSupply potentials (layers 1-2)
  kernel  RootKernelLedger internals via kernel_ledger_daily converter
  canopy  PlantGro canopy/stress variables
  flows   NAcceptance / NFlux / OrganNState reserve flows

Usage: .venv/bin/python tools/diagnostics/run_s3_s4.py [--out-dir DIR]
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DIAG = REPO / "tools/diagnostics"
PY = sys.executable

AB = REPO / "workspace/runs/v4root_ab_diag_20261108"
S4 = REPO / "workspace/runs/s4_diag_20261108"
META = REPO / "data/user/experiments/xxql2601_final_sasc70_20261106" \
    "/treatment_metadata.csv"
COMPARISON = REPO / "fixtures/v7-26sp/comparison.csv"

VARIANTS = {
    "s1": AB / "replay_s1",
    "s3": AB / "replay_s3",
    "s4": S4 / "replay_s4_k2_state2",
    "k1s2": S4 / "replay_s4_k1_state2",
}
LABELS = {
    "s1": "S1 (k1,state1) calibrated replay",
    "s3": "S3 (k2,state1) v4-R2 kernel",
    "s4": "S4 (k2,state2) fused psi*",
    "k1s2": "(k1,state2) state-only attribution",
}


def run(cmd, out=None, clean=True):
    # Toolkit contract: figure out dirs must NOT pre-exist (it never
    # overwrites figures). clean=False skips dir handling entirely (used
    # for the converter step whose target lives inside a work case-dir).
    if out is not None and clean:
        if out.exists():
            shutil.rmtree(out)
        out.parent.mkdir(parents=True, exist_ok=True)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"  FAILED: {' '.join(map(str, cmd))}")
        print(res.stdout[-800:], res.stderr[-800:])
    return res.returncode


def daily(case_dir, out, fields, label, layer=None, file_name=None):
    cmd = [PY, str(DIAG / "diagnostics.py"), "daily",
           "--case-dir", str(case_dir), "--season", "26SP",
           "--metadata", str(META), "--label", label,
           "--file", file_name]
    for f in fields:
        cmd += ["--field", f]
    if layer is not None:
        cmd += ["--layer", str(layer)]
    cmd += ["--out", str(out)]
    return run(cmd, out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir",
                   default="workspace/runs/diagnostics_s3s4_20261109")
    a = ap.parse_args()
    out_root = (REPO / a.out_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    # --- A. yield, 4 variants, observed when possible ----------------
    for tag, case in VARIANTS.items():
        out = out_root / "yield" / tag
        base = [PY, str(DIAG / "diagnostics.py"), "yield",
                "--case-dir", str(case), "--season", "26SP",
                "--metadata", str(META),
                "--label", LABELS[tag], "--out", str(out)]
        if run(base + ["--comparison", str(COMPARISON)], out) != 0:
            print(f"  [{tag}] observed attach failed; sim-only retry")
            run(base, out)

    # --- B. psi family -------------------------------------------------
    daily(VARIANTS["s3"], out_root / "psi" / "s3_total_uptake",
          ["total_psi", "uptake_psi"], "S3 psi (total & uptake)",
          file_name="NDecision.csv")
    daily(VARIANTS["s4"], out_root / "psi" / "s4_star_nni",
          ["psi_star", "nni_func", "uptake_psi"],
          "S4 fused psi* / NNI_f / uptake psi",
          file_name="NStatePsi.csv")

    # --- C. per-layer root supply --------------------------------------
    for tag in ("s3", "s4"):
        for layer in (1, 2):
            daily(VARIANTS[tag],
                  out_root / "root" / f"{tag}_layer{layer}",
                  ["kinetic_potential_kgN_ha",
                   "stock_limited_potential_kgN_ha", "actual_kgN_ha"],
                  f"{LABELS[tag]} · layer {layer}", layer=layer,
                  file_name="RootNSupply.csv")

    # --- D. kernel internals (converted ledger) ------------------------
    work = out_root / "_work"
    work.mkdir(exist_ok=True)
    for tag in ("s3", "s4"):
        case = work / tag
        case.mkdir(exist_ok=True)
        if not (case / "PlantGro.OUT").exists():
            shutil.copy2(VARIANTS[tag] / "PlantGro.OUT",
                         case / "PlantGro.OUT")
        conv = case / "RootKernelDaily.csv"
        run([PY, str(DIAG / "kernel_ledger_daily.py"),
             "--ledger", str(VARIANTS[tag] / "RootKernelLedger.csv"),
             "--decision", str(VARIANTS[tag] / "NDecision.csv"),
             "--out", str(conv)], clean=False)
        daily(case, out_root / "kernel" / f"{tag}_supply",
              ["mf_g_m2_d", "diffusion_g_m2_d", "uptake_g_m2_d"],
              f"{LABELS[tag]} · kernel supply", layer=1,
              file_name="RootKernelDaily.csv")
        daily(case, out_root / "kernel" / f"{tag}_surface",
              ["cr_mgN_L", "poolfactor"],
              f"{LABELS[tag]} · rhizosphere & feedback", layer=1,
              file_name="RootKernelDaily.csv")

    # --- E. canopy & stress --------------------------------------------
    for tag in ("s3", "s4"):
        daily(VARIANTS[tag], out_root / "canopy" / tag,
              ["LAID:m2/m2", "LWAD:kg/ha", "SWAD:kg/ha", "NSTD",
               "WSPD"], f"{LABELS[tag]} · canopy & stress",
              file_name="PlantGro.OUT")

    # --- F. reserve flows ------------------------------------------------
    for tag in ("s3", "s4"):
        daily(VARIANTS[tag], out_root / "flows" / f"{tag}_acceptance",
              ["root_provisional", "root_accepted", "root_rejected"],
              f"{LABELS[tag]} · root acceptance",
              file_name="NAcceptance.csv")
        daily(VARIANTS[tag], out_root / "flows" / f"{tag}_flux",
              ["leaf_mobilized", "leaf_repaired", "leaf_stored",
               "leaf_reserve_lost"],
              f"{LABELS[tag]} · leaf reserve flux",
              file_name="NFlux.csv")
        daily(VARIANTS[tag], out_root / "flows" / f"{tag}_organstate",
              ["leaf_n", "stem_n", "leaf_reserve", "leaf_critical"],
              f"{LABELS[tag]} · organ N state",
              file_name="OrganNState.csv")

    print(f"\nbatch complete -> {out_root}")


if __name__ == "__main__":
    main()
