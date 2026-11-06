"""Rebuild calibration batches on the DMFR-corrected observations (20260808).

The TMT dry-weight fix (TN13 DMFR 9.31%->3.21%, TN5 6.35%->4.20%) changed the
bundle's input_manifest.json SHA-256, so every calibration PST built before
2026-08-07 must be rebuilt against the corrected bundle.  This script
reconstructs the design json (updated bundle_manifest_sha256, new date suffix)
and builds the PST via build_pest.py.

Rebuilds:
  - batch B (rawdiff_terminal nresp, 108/101 organ_n, NREXP/NRMIN adjustable)
  - the four custom DSSAT versions: a3, a3_nr_zp, nni, nresp

Usage:
    python tools/calibration/rebuild_calibration_after_dmfr_fix_20260808.py \
        [--version nresp|a3|a3_nr_zp|nni]   (default: all five)

The DMFR-corrected bundle is xxql2501_layermean_ic_valid_n012_v1_20260801
(already synced on 2026-08-07).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
DATE = "20260808"
BUNDLE = ROOT / "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801"
BOUNDS_ID = "eggplant_e02_v2_nresp_wide_nrexp_20260806"
POLICY = ROOT / "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260805.csv"
GROUP_POLICY = ROOT / "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260805.csv"
DESIGN_TEMPLATE = ROOT / "configs/runs/eggplant_e02_v2_rawdiff_terminal_nresp_wide_20260806.json"

# Version -> exe dir, SPE dir, custom params to inject (name -> init/lower/upper)
VERSIONS = {
    "nresp": {
        "exe_dir": "windows_nresp_20260806",
        "custom_params": {},  # NREXP/NRMIN already in bounds
    },
    "a3": {
        "exe_dir": "windows_a3_20260806",
        "custom_params": {"NUPK50": (8.664, 1.0, 40.0), "NUPCMN": (0.50, 0.0, 2.0)},
    },
    "a3_nr_zp": {
        "exe_dir": "windows_a3_nr_zp_20260806",
        "custom_params": {"NUPK50": (8.664, 1.0, 40.0), "NUPCMN": (0.50, 0.0, 2.0)},
    },
    "nni": {
        "exe_dir": "windows_nni_20260806",
        "custom_params": {"NUPK50": (40.0, 1.0, 40.0), "NUPQ": (1.00, 0.50, 1.50)},
    },
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _new_design(version: str, case: str, exe: Path, spe: Path) -> Path:
    design = json.loads(DESIGN_TEMPLATE.read_text(encoding="utf-8"))
    design["design_id"] = f"eggplant_e02_v2_rawdiff_terminal_{version}_dmfrfix_{DATE}"
    design["custom_dssat_executable"] = str(exe.resolve())
    design["custom_spe"] = str(spe.resolve())
    design["formal"] = {"n_reals": 150, "noptmax": 4, "initial_ensemble_method": "sobol"}
    design["seasons"][0]["bundle_manifest_sha256"] = _sha256(BUNDLE / "input_manifest.json")
    design["seasons"][0]["bundle_path"] = str(BUNDLE)
    path = ROOT / "configs/runs" / f"eggplant_e02_v2_rawdiff_terminal_{version}_dmfrfix_{DATE}.json"
    path.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def build_version(version: str) -> Path:
    info = VERSIONS[version]
    exe_dir = ROOT / "windows" / info["exe_dir"]
    exe = exe_dir / "DSCSM048.EXE"
    spe = exe_dir / "Genotype/TMGRO048.SPE"
    if not exe.is_file():
        raise FileNotFoundError(exe)
    if not spe.is_file():
        raise FileNotFoundError(spe)

    case = f"e02_v2_rawdiff_terminal_{version}_108par_150x4_{DATE}"
    out_dir = ROOT / "workspace/runs" / case
    if out_dir.exists():
        raise FileExistsError(f"target exists: {out_dir}")

    design_path = _new_design(version, case, exe, spe)
    out_dir.mkdir(parents=True)

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
        "--random-seed", DATE,
        "--bad-phi-sigma", "1e300",
        "--batch", str(BUNDLE / "DSSBatch.v48"),
        "--harvest-var", "CHPDT",
        "--include-soil",
        "--out-dir", str(out_dir),
        "--param-review-mode", "off", "--bounds-review-mode", "off",
        "--observation-policy-csv", str(POLICY),
        "--initial-ensemble-method", "sobol",
        "--no-include-n-uptake",
    ]
    print(f"\n[{version}] building base PST...")
    subprocess.run(cmd, cwd=str(ROOT), env=env, check=True)

    # Inject custom N-uptake parameters (per version)
    pst = pyemu.Pst(str(out_dir / f"{case}.pst"))
    custom = info["custom_params"]
    if custom:
        print(f"[{version}] injecting: {list(custom)}")
        existing = set(pst.parameter_data.index.astype(str).str.lower())
        new_rows = []
        for name, (init, lower, upper) in custom.items():
            if name.lower() in existing:
                continue
            new_rows.append({
                "partrans": "none", "parchglim": "factor",
                "parval1": init, "parlbnd": lower, "parubnd": upper,
                "pargp": "species", "scale": 1.0, "offset": 0.0, "dercom": 1, "extra": "",
            })
        if new_rows:
            names = [n.lower() for n in custom if n.lower() not in existing]
            new_df = pd.DataFrame(new_rows, index=names)
            new_df = new_df.reindex(columns=pst.parameter_data.columns)
            new_df["parnme"] = new_df.index
            pst.parameter_data = pd.concat([pst.parameter_data, new_df])

            tpl = out_dir / f"{case}_params.csv.tpl"
            lines = tpl.read_text(encoding="utf-8").splitlines()
            for name in custom:
                if not any(l.lower().startswith(name.lower() + ",") for l in lines):
                    lines.append(f"{name},~ {name} ~")
            tpl.write_text("\n".join(lines) + "\n", encoding="utf-8")

            params = pd.read_csv(out_dir / f"{case}_params.csv")
            for name, (init, _, _) in custom.items():
                if name.upper() not in params["name"].astype(str).str.upper().values:
                    params = pd.concat([params, pd.DataFrame([{"name": name.upper(), "value": init}])], ignore_index=True)
            params.to_csv(out_dir / f"{case}_params.csv", index=False)

    # Design json inside run dir + model command
    run_design = out_dir / "six_treatment_design.json"
    design = json.loads(design_path.read_text(encoding="utf-8"))
    run_design.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pst.model_command = [
        f'python "{(ROOT / "src/calibration/run_multiseason.py").as_posix()}" '
        f'--design "{run_design.as_posix()}" '
        f'--param-csv {case}_params.csv --harvest-var CHPDT '
        f'--keep-nitrogen-outputs --prefix {case}'
    ]
    pst.control_data.noptmax = 4
    pst.pestpp_options["ies_num_reals"] = "150"
    pst.pestpp_options["rand_seed"] = DATE
    pst.write(str(out_dir / f"{case}.pst"))

    # Verify
    pst = pyemu.Pst(str(out_dir / f"{case}.pst"))
    print(f"[{version}] verify: npar={pst.npar} npar_adj={pst.npar_adj} nobs={pst.nobs}")
    for p in [n.lower() for n in custom] + ["nrexp", "nrmin"]:
        if p in pst.parameter_data.index:
            r = pst.parameter_data.loc[p]
            print(f"  {p}: trans={r.partrans} init={r.parval1} [{r.parlbnd}, {r.parubnd}]")

    receipt = {
        "run_id": case,
        "version": version,
        "built_on": DATE,
        "bundle": str(BUNDLE),
        "bundle_manifest_sha256": _sha256(BUNDLE / "input_manifest.json"),
        "custom_dssat": str(exe.resolve()),
        "custom_spe": str(spe.resolve()),
        "n_parameters": int(pst.npar),
        "n_parameters_adjustable": int(pst.npar_adj),
        "n_observations": int(pst.nobs),
        "n_active_observations": int((pst.observation_data["weight"].astype(float) > 0).sum()),
        "n_reals": 150,
        "noptmax": 4,
        "custom_params_injected": list(custom.keys()),
        "note": "DMFR-corrected bundle (TN13 9.31%->3.21%, TN5 6.35%->4.20%)",
    }
    (out_dir / "formal_launch_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[{version}] done: {out_dir.name}")
    return out_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", choices=list(VERSIONS), default=None)
    args = parser.parse_args()
    to_build = [args.version] if args.version else list(VERSIONS)
    built = []
    for v in to_build:
        try:
            built.append(build_version(v))
        except Exception as e:
            print(f"\nERROR building {v}: {e}", file=sys.stderr)
            if args.version:
                return 1
    print(f"\n{'='*60}")
    print(f"Built {len(built)} cases on {DATE} (DMFR-corrected bundle):")
    for d in built:
        print(f"  {d.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
