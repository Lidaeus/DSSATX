#!/usr/bin/env python3
"""replay_calibrated.py -- deterministic replay of the calibrated best
members (S1 kernel-1 params on the S1 binary, S3 kernel-2 params on the
S3 v4root binary), retaining full daily outputs for diagnostics.

Writes replayed outputs to --out-dir/replay_{s1,s3}/ and a manifest.
"""
import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
VARIANT = Path(__file__).resolve().parent
KEEP = [
    "Evaluate.OUT", "PlantGro.OUT", "PlantN.OUT", "Summary.OUT",
    "RootNSupply.csv", "NDecision.csv", "NAcceptance.csv", "NFlux.csv",
    "OrganNState.csv", "RootKernelLedger.csv", "WARNING.OUT",
]


def best_member(phi_csv: Path):
    with phi_csv.open(newline="") as f:
        rows = list(csv.DictReader(f))
    last = rows[-1]
    fixed = {"iteration", "total_runs", "mean", "standard_deviation",
             "min", "max"}
    best, bv = None, float("inf")
    for m in last:
        if m in fixed or last[m] in ("", None):
            continue
        v = float(last[m])
        if v < bv:
            best, bv = m, v
    return best, bv


def member_params(ens_csv: Path, member: str, out_csv: Path):
    with ens_csv.open(newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        row = None
        for r in reader:
            if r["real_name"] == member:
                row = r
                break
    if row is None:
        raise SystemExit(f"member {member} not in {ens_csv}")
    with out_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "value"])
        for name in fields[1:]:
            w.writerow([name, row[name]])


def run_replay(tag, exe, params_csv, case_dir, out_dir, env_extra):
    work = out_dir / f"work_{tag}"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(
        case_dir, work,
        ignore=shutil.ignore_patterns(
            "_agents", "_iso_runs", "*.rec", "*.rns", "*.jco", "*.log",
            "quality_report*", "ies_quality", "run_status.json", "manager",
            "state"))
    shutil.copy2(params_csv, work / "macsmk50x4_params.csv")
    env = dict(os.environ)
    env["PATH"] = f"{REPO}/.venv/bin:" + env["PATH"]
    env["DSSAT_CUSTOM_EXE"] = str(exe)
    env["DSSAT_STD_DATA_DIR"] = str(
        REPO / ".local/v15s1-inputs/dssat-std")
    env["DSSAT_SPE_BASE"] = str(
        REPO / ".local/v15s1-inputs/TMGRO048.SPE.base")
    env["DSSAT_KEEP_RUNS"] = "1"
    env.update(env_extra)
    cmd = [sys.executable, str(REPO / "src/calibration/run_dssat.py"),
           "--param-csv", "macsmk50x4_params.csv", "--batch",
           "DSSBatch.v48", "--harvest-var", "CHPDT",
           "--input-dir",
           str(REPO
               / "data/user/experiments/xxql2601_final_sasc70_20261106")]
    res = subprocess.run(cmd, cwd=work, env=env, capture_output=True,
                         text=True, timeout=900)
    if res.returncode != 0:
        print(res.stdout[-1500:], res.stderr[-1500:])
        raise SystemExit(f"replay failed for {tag}")
    iso = sorted((work / "_iso_runs").glob("run_*"))[-1]
    dest = out_dir / f"replay_{tag}"
    dest.mkdir(parents=True, exist_ok=True)
    for name in KEEP:
        src = iso / name
        if src.is_file():
            shutil.copy2(src, dest / name)
    shutil.rmtree(work)
    return dest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    s1_dir = REPO / "workspace/runs/v15s1_smoke_50x4_20261107"
    s3_dir = REPO / "workspace/runs/v15s3_r2_smoke_50x4_20261107"
    manifest = {}
    for tag, run_dir, prefix, exe, env_extra in [
        ("s1", s1_dir, "macsmk50x4",
         REPO / ".local/build-v15s1/bin/dscsm048", {}),
        ("s3", s3_dir, "s3r2smk50x4",
         REPO / ".local/build-v15-s3-v4root/bin/dscsm048",
         {"DSSAT_ROOT_UPTAKE_NML":
          str(VARIANT / "RootUptake.nml.template")}),
    ]:
        member, phi = best_member(run_dir / f"{prefix}.phi.actual.csv")
        params = out_dir / f"best_params_{tag}.csv"
        member_params(run_dir / f"{prefix}.4.par.csv", member, params)
        dest = run_replay(tag, exe, params, run_dir, out_dir, env_extra)
        manifest[tag] = {"member": member, "phi": phi,
                         "params": params.name, "replay": str(dest)}
        print(f"{tag}: member={member} phi={phi:.2f} -> {dest}")
    (out_dir / "replay_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
