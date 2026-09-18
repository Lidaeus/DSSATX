"""Build four calibration cases for the four custom DSSAT N-response versions (20260806).

Uses batch B's configuration (rawdiff_terminal objective, full 108/101 organ_n params,
NREXP/NRMIN adjustable with widened lower bound 0.1) but swaps the DSSAT executable
and SPE template per version, and injects the version-specific N-uptake parameters.

Four versions:
  - a3:       A3 threshold N uptake (NUPK50, NUPCMN); native NSTRES
  - a3_nr_zp: A3 + zero-hold NR response (NUPK50, NUPCMN, NREXP, NRMIN)
  - nni:      native uptake + 10% NNI critical dilution (NUPK50, NUPQ; NQMAX read-only)
  - nresp:    native uptake + continuous NR response (NREXP, NRMIN)

Usage:
    python tools/calibration/build_four_custom_dssat_20260807.py [--version VERSION]

Without --version, builds all four.  With --version, builds only one.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]

# ── Batch B base config (reused objective + bounds) ──────────────────────────
DESIGN_TEMPLATE = ROOT / "configs/runs/eggplant_e02_v2_rawdiff_terminal_nresp_wide_20260806.json"
BOUNDS_ID = "eggplant_e02_v2_nresp_wide_nrexp_20260806"
POLICY = ROOT / "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260805.csv"
BUNDLE = ROOT / "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801"

# ── Four custom DSSAT versions ───────────────────────────────────────────────
# Each entry: (version_key, exe_dir, n_uptake_params_to_inject)
# n_uptake_params: dict of {name: (init, lower, upper)} for parameters NOT in
# the frozen bounds that must be manually added to the PST.
VERSIONS = {
    "a3": {
        "exe_dir": "windows_a3_20260806",
        "title": "A3 阈值氮吸收 (NUPK50+NUPCMN, 原生NSTRES)",
        "custom_params": {
            # A3 SPE row: "8.664  0.50   NUPK50,NUPCMN"
            "NUPK50": (8.664, 1.0, 40.0),
            "NUPCMN": (0.50, 0.0, 2.0),
        },
    },
    "a3_nr_zp": {
        "exe_dir": "windows_a3_nr_zp_20260806",
        "title": "A3+零保持NR响应 (NUPK50+NUPCMN+NREXP+NRMIN)",
        "custom_params": {
            "NUPK50": (8.664, 1.0, 40.0),
            "NUPCMN": (0.50, 0.0, 2.0),
            # NREXP/NRMIN are already in the frozen bounds (adjustable 0.1-1.0 / 0.1-0.8)
        },
    },
    "nni": {
        "exe_dir": "windows_nni_20260806",
        "title": "NNI 临界氮稀释验证 (NUPK50+NUPQ, NQMAX只读)",
        "custom_params": {
            # NNI SPE row: "40.0  1.00   NUPK50,NUPQ"
            "NUPK50": (40.0, 1.0, 40.0),
            "NUPQ": (1.00, 0.50, 1.50),
        },
    },
    "nresp": {
        "exe_dir": "windows_nresp_20260806",
        "title": "原生吸收+连续NR响应 (NREXP+NRMIN)",
        "custom_params": {
            # NRESP SPE row: "40.0  1.00   NUPK50,NUPQ" — but these are native
            # uptake, not the custom N-response mechanism. NREXP/NRMIN are
            # already in frozen bounds. No extra injection needed.
        },
    },
}


def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_version(version_key: str) -> Path:
    info = VERSIONS[version_key]
    exe_dir = ROOT / "windows" / info["exe_dir"]
    exe = exe_dir / "DSCSM048.EXE"
    spe = exe_dir / "Genotype/TMGRO048.SPE"

    if not exe.is_file():
        raise FileNotFoundError(f"exe not found: {exe}")
    if not spe.is_file():
        raise FileNotFoundError(f"SPE not found: {spe}")

    case = f"e02_v2_rawdiff_terminal_{version_key}_108par_150x4_20260807"
    out_dir = ROOT / "workspace/runs" / case
    if out_dir.exists():
        raise FileExistsError(f"target exists: {out_dir}")

    # Create a version-specific design json
    design = json.loads(DESIGN_TEMPLATE.read_text(encoding="utf-8"))
    design["design_id"] = f"eggplant_e02_v2_rawdiff_terminal_{version_key}_20260807"
    design["custom_dssat_executable"] = str(exe.resolve())
    design["custom_spe"] = str(spe.resolve())
    design["formal"] = {"n_reals": 150, "noptmax": 4, "initial_ensemble_method": "sobol"}
    design_path = ROOT / "configs/runs" / f"eggplant_e02_v2_rawdiff_terminal_{version_key}_20260807.json"
    out_dir.mkdir(parents=True)

    # Step 1: build the base PST with build_pest.py
    env = os.environ.copy()
    env["DSSAT_SPE_BASE"] = str(spe.resolve())
    cmd = [
        sys.executable, str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2",
        "--multiseason-design", str(design_path),
        "--input-dir", str(BUNDLE),
        "--bounds-id", BOUNDS_ID, "--bounds-crop", "eggplant",
        "--prefix", case,
        "--noptmax", "4", "--ies-num-reals", "150",
        "--random-seed", "20260807",
        "--bad-phi-sigma", "1e300",
        "--batch", str(BUNDLE / "DSSBatch.v48"),
        "--harvest-var", "CHPDT",
        "--include-soil", "--out-dir", str(out_dir),
        "--param-review-mode", "off", "--bounds-review-mode", "off",
        "--observation-policy-csv", str(POLICY),
        "--initial-ensemble-method", "sobol",
        # Disable automatic NUPT parsing: the SPE rows in these custom builds
        # have only 2-param NUPT rows (NUPK50,NUPCMN or NUPK50,NUPQ), which the
        # 3-param parser in build_pest.py cannot handle and produces NaN rows.
        # Custom N-uptake parameters are injected manually in step 2.
        "--no-include-n-uptake",
    ]
    print(f"\n[{version_key}] building base PST...")
    design_path.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    subprocess.run(cmd, cwd=str(ROOT), env=env, check=True)

    # Step 2: inject version-specific custom parameters
    custom = info["custom_params"]
    pst = pyemu.Pst(str(out_dir / f"{case}.pst"))
    if custom:
        print(f"[{version_key}] injecting custom params: {list(custom.keys())}")
        existing = set(pst.parameter_data.index.astype(str).str.lower())
        new_rows = []
        for name, (init, lower, upper) in custom.items():
            if name.lower() in existing:
                print(f"  {name} already in PST, skipping injection")
                continue
            new_rows.append({
                "partrans": "none", "parchglim": "factor",
                "parval1": init, "parlbnd": lower, "parubnd": upper,
                "pargp": "species", "scale": 1.0, "offset": 0.0, "dercom": 1, "extra": "",
            })
        if new_rows:
            # Build the new rows with the SAME columns as the existing
            # parameter_data. parnme is BOTH the index and a column in pyemu's
            # Pst; the column must be populated (not NaN) or pst.write fails.
            names = [n.lower() for n in custom if n.lower() not in existing]
            new_df = pd.DataFrame(new_rows, index=names)
            new_df = new_df.reindex(columns=pst.parameter_data.columns)
            new_df["parnme"] = new_df.index
            pst.parameter_data = pd.concat([pst.parameter_data, new_df])

            # Add to params.csv.tpl
            tpl = out_dir / f"{case}_params.csv.tpl"
            lines = tpl.read_text(encoding="utf-8").splitlines()
            for name in custom:
                if not any(line.lower().startswith(name.lower() + ",") for line in lines):
                    lines.append(f"{name},~ {name} ~")
            tpl.write_text("\n".join(lines) + "\n", encoding="utf-8")

            # Add to params.csv
            params = pd.read_csv(out_dir / f"{case}_params.csv")
            for name, (init, _, _) in custom.items():
                if name.upper() not in params["name"].astype(str).str.upper().values:
                    params = pd.concat([params, pd.DataFrame([{"name": name.upper(), "value": init}])], ignore_index=True)
            params.to_csv(out_dir / f"{case}_params.csv", index=False)

    # Update model_command to include the design json
    # The design must live INSIDE the run dir as six_treatment_design.json
    # (run_multiseason.py resolves it relative to the run dir).
    run_design = out_dir / "six_treatment_design.json"
    run_design.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pst.model_command = [
        f'python "{(ROOT / "src/calibration/run_multiseason.py").as_posix()}" '
        f'--design "{run_design.as_posix()}" '
        f'--param-csv {case}_params.csv --harvest-var CHPDT '
        f'--keep-nitrogen-outputs --prefix {case}'
    ]
    pst.control_data.noptmax = 4
    pst.pestpp_options["ies_num_reals"] = "150"
    pst.pestpp_options["rand_seed"] = "20260807"
    pst.write(str(out_dir / f"{case}.pst"))

    # Step 3: Verify
    pst = pyemu.Pst(str(out_dir / f"{case}.pst"))
    print(f"[{version_key}] verify: npar={pst.npar} npar_adj={pst.npar_adj} nobs={pst.nobs}")
    for p in [n.lower() for n in info["custom_params"]] + ["nrexp", "nrmin"]:
        if p in pst.parameter_data.index:
            r = pst.parameter_data.loc[p]
            print(f"  {p}: trans={r.partrans} init={r.parval1} [{r.parlbnd}, {r.parubnd}]")

    # Write a launch receipt
    receipt = {
        "run_id": case,
        "version": version_key,
        "title": info["title"],
        "custom_dssat": str(exe.resolve()),
        "custom_spe": str(spe.resolve()),
        "exe_sha256": _sha256(exe),
        "n_parameters": int(pst.npar),
        "n_parameters_adjustable": int(pst.npar_adj),
        "n_observations": int(pst.nobs),
        "n_active_observations": int((pst.observation_data["weight"].astype(float) > 0).sum()),
        "n_reals": 150,
        "noptmax": 4,
        "custom_params_injected": list(info["custom_params"].keys()),
    }
    (out_dir / "formal_launch_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[{version_key}] done: {out_dir.name}")
    return out_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Build four custom DSSAT calibration cases")
    parser.add_argument("--version", choices=list(VERSIONS), default=None,
                        help="Build only one version (default: all four)")
    args = parser.parse_args()

    to_build = [args.version] if args.version else list(VERSIONS)
    built = []
    for vk in to_build:
        try:
            built.append(build_version(vk))
        except Exception as e:
            print(f"\nERROR building {vk}: {e}", file=sys.stderr)
            if args.version:
                return 1
    print(f"\n{'='*60}")
    print(f"Built {len(built)} cases:")
    for d in built:
        print(f"  {d.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
