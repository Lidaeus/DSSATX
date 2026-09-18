"""Build batch B: rawdiff_terminal objective with full 108/101 organ_n params + NREXP/NRMIN adjustable.

This is the "mixed config" batch for comparison with batch A:
  - Objective function: rawdiff_terminal (signed_difference_plus_terminal + raw_difference N response)
  - Parameter set: 108 total / 101 adjustable (full organ_n, from eggplant_e02_v2_nresp_wide_nrexp_20260806 bounds)
  - NREXP/NRMIN: adjustable with widened lower bound 0.1
  - DSSAT exe: dscsm048_nresp.exe (N-response via SPE XPODF row)
  - N_RESPONSE budget=0.10, SOIL_WATER budget=0.20 (already low in rawdiff_terminal policy)

Contrast with batch A which used the OLD objective (canopy_yield_nresponse, log transforms) with
N_RESPONSE/SOIL_WATER weights reduced to 1/3.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pyemu


ROOT = Path(__file__).resolve().parents[2]
CASE = "e02_v2_rawdiff_terminal_nresp01_soil02_nresp_108par_150x4_20260806"
OUT = ROOT / "workspace/runs" / CASE
DESIGN = ROOT / "configs/runs/eggplant_e02_v2_rawdiff_terminal_nresp_wide_20260806.json"
BOUNDS_ID = "eggplant_e02_v2_nresp_wide_nrexp_20260806"
POLICY = ROOT / "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260805.csv"
BUNDLE = ROOT / "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801"
# N-response DSSAT exe (XPODF row with NREXP/NRMIN) — same as batch A
EXE = ROOT / "windows/windows_nresp_20260803/dscsm048_nresp.exe"
SPE = ROOT / "windows/windows_nresp_20260803/Genotype/TMGRO048.SPE"


def main() -> None:
    if OUT.exists():
        raise FileExistsError(OUT)
    if not EXE.is_file():
        raise FileNotFoundError(f"nresp exe not found: {EXE}")
    if not SPE.is_file():
        raise FileNotFoundError(f"nresp SPE not found: {SPE}")

    env = os.environ.copy()
    # Tell build_pest to use the nresp SPE template (contains XPODF,NSTFAC,NREXP,NRMIN row)
    env["DSSAT_SPE_BASE"] = str(SPE.resolve())

    cmd = [
        sys.executable, str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2",
        "--multiseason-design", str(DESIGN),
        "--input-dir", str(BUNDLE),
        "--bounds-id", BOUNDS_ID, "--bounds-crop", "eggplant",
        "--prefix", CASE,
        "--noptmax", "4", "--ies-num-reals", "150",
        "--random-seed", "20260806",
        "--bad-phi-sigma", "1e300",
        "--batch", str(BUNDLE / "DSSBatch.v48"),
        "--harvest-var", "CHPDT",
        # NOTE: --include-n-uptake is OMITTED (that's for the a3 exe's NUPK50/NUPCMN;
        #       nresp exe uses NREXP/NRMIN via SPE XPODF row, already in our bounds)
        "--include-soil",
        "--out-dir", str(OUT),
        "--param-review-mode", "off", "--bounds-review-mode", "off",
        "--observation-policy-csv", str(POLICY),
        "--initial-ensemble-method", "sobol",
    ]
    print(f"[build] constructing PST for {CASE}")
    print(f"[build] design:      {DESIGN.name}")
    print(f"[build] bounds:      {BOUNDS_ID}")
    print(f"[build] DSSAT_SPE_BASE: {SPE}")
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)

    # Verify the PST
    pst = pyemu.Pst(str(OUT / f"{CASE}.pst"))
    print(f"\n[verify] npar={pst.npar} npar_adj={pst.npar_adj} nobs={pst.nobs}")
    print(f"[verify] noptmax={pst.control_data.noptmax} ies_num_reals={pst.pestpp_options.get('ies_num_reals')}")

    # Confirm NREXP/NRMIN are present and adjustable with widened bounds
    for p in ("nrexp", "nrmin"):
        if p in pst.parameter_data.index:
            row = pst.parameter_data.loc[p]
            print(f"[verify] {p}: trans={row.partrans} init={row.parval1} bounds=[{row.parlbnd}, {row.parubnd}]")
        else:
            print(f"[verify] WARNING: {p} not found in parameter data!")

    # Confirm process_state_objective generated the expected tokens
    obs_tokens = set(pst.observation_data.obgnme.astype(str).str.upper().unique())
    has_increment = any("LAIDDM" in t or "LWADDM" in t for t in obs_tokens)
    has_terminal = any("LAIETM" in t or "LWETM" in t for t in obs_tokens)
    has_nresp = any("NRESP" in t for t in obs_tokens)
    print(f"[verify] CANOPY_INCREMENT tokens: {has_increment}")
    print(f"[verify] CANOPY_TERMINAL tokens:  {has_terminal}")
    print(f"[verify] N_RESPONSE tokens:       {has_nresp}")
    print(f"\n[done] PST ready at: {OUT}")


if __name__ == "__main__":
    main()
