#!/usr/bin/env python3
"""eval_ab_forward.py -- deterministic forward A/B: S1 vs S3(v4-R2) root
kernel on the xxql2601_final_sasc70 bundle (12 W x N treatments).

Runs the calibration forward wrapper once per binary with the SAME
baseline parameter set, then extracts per-treatment season outcomes from
Summary.OUT and writes an evidence CSV (engineering_validated only).

Usage (from repo root, venv active):
  python subprojects/critical_n/n_buffer_v15/source/v15_s3_v4root/eval_ab_forward.py \
    --run-dir workspace/runs/v15s1_smoke_50x4_20261107 \
    --out .local/v4root-ab-forward.csv
"""
import argparse
import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
VARIANT = Path(__file__).resolve().parent
SUM_COLS = {
    "CWAMS": "aboveground_kg_ha",
    "PWAMS": "fruit_weight_kg_ha",
    "CNAMS": "plant_n_kg_ha",
}


def parse_summary(path: Path):
    rows = []
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        lines = [ln.rstrip("\n") for ln in f]
    header = None
    for i, ln in enumerate(lines):
        if ln.startswith("@"):
            header = ln[1:].split()
            data = [l.split() for l in lines[i + 1:] if l.strip()]
            for parts in data:
                rows.append(dict(zip(header, parts)))
            break
    return rows


def run_forward(tag: str, exe: Path, workroot: Path, env_extra: dict):
    src = workroot
    work = workroot.parent / f"_ab_{tag}"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(src, work,
                    ignore=shutil.ignore_patterns("_agents", "_iso_runs",
                                                  "*.rec", "*.rns", "*.jco",
                                                  "*.log"))
    env = dict(os.environ)
    env["PATH"] = f"{REPO}/.venv/bin:" + env["PATH"]
    env["DSSAT_CUSTOM_EXE"] = str(exe)
    env["DSSAT_STD_DATA_DIR"] = str(REPO / ".local/v15s1-inputs/dssat-std")
    env["DSSAT_SPE_BASE"] = str(REPO / ".local/v15s1-inputs/TMGRO048.SPE.base")
    env.update(env_extra)
    cmd = [sys.executable, str(REPO / "src/calibration/run_dssat.py"),
           "--param-csv", "macsmk50x4_params.csv", "--batch", "DSSBatch.v48",
           "--harvest-var", "CHPDT",
           "--input-dir",
           str(REPO / "data/user/experiments/xxql2601_final_sasc70_20261106")]
    res = subprocess.run(cmd, cwd=work, env=env, capture_output=True,
                         text=True, timeout=600)
    if res.returncode != 0:
        print(res.stdout[-2000:])
        print(res.stderr[-2000:])
        raise SystemExit(f"forward run failed for {tag}")
    return work, parse_summary(work / "Evaluate.OUT")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True,
                    help="existing PEST case dir with macsmk50x4_params.csv")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    workroot = Path(args.run_dir).resolve()
    s1_exe = REPO / ".local/build-v15s1/bin/dscsm048"
    s3_exe = REPO / ".local/build-v15-s3-v4root/bin/dscsm048"
    nml = VARIANT / "RootUptake.nml.template"

    _, sum_s1 = run_forward("s1", s1_exe, workroot, {})
    _, sum_s3 = run_forward("s3", s3_exe, workroot,
                            {"DSSAT_ROOT_UPTAKE_NML": str(nml)})

    meta = {}
    with (REPO / "data/user/experiments/xxql2601_final_sasc70_20261106"
          / "treatment_metadata.csv").open(newline="") as f:
        for row in csv.DictReader(f):
            meta[int(row["treatment"])] = row

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["run", "trt", "trt_label", "water_level",
                    "nitrogen_level",
                    *[f"s1_{v}" for v in SUM_COLS.values()],
                    *[f"s3_{v}" for v in SUM_COLS.values()],
                    *[f"ratio_{v}" for v in SUM_COLS.values()]])
        for r1, r3 in zip(sum_s1, sum_s3):
            trt = int(r1.get("TN", 0) or 0)
            m = meta.get(trt, {})
            vals1 = {k: float(r1[k]) for k in SUM_COLS if k in r1}
            vals3 = {k: float(r3[k]) for k in SUM_COLS if k in r3}
            row = [1, trt, m.get("treatment_label", ""),
                   m.get("water_level", ""), m.get("nitrogen_level", "")]
            row += [vals1.get(k, float("nan")) for k in SUM_COLS]
            row += [vals3.get(k, float("nan")) for k in SUM_COLS]
            row += [(vals3[k] / vals1[k] if vals1.get(k, 0) else float("nan"))
                    for k in SUM_COLS]
            w.writerow(row)
    print(f"wrote {out} ({len(sum_s1)} treatments)")


if __name__ == "__main__":
    main()
