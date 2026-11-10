#!/usr/bin/env python3
"""kernel_ledger_daily.py -- convert RootKernelLedger.csv (v15_s3_v4root
kernel internals: day_index,layer,...) into the run,yrdoy-keyed long form
that tools/diagnostics/diagnostics.py daily consumes.

Block structure: day_index resets at each run; block i (0-based) is run
i+1. Day d of a run maps to the d-th NDecision row of that treatment.
"""
import argparse
import csv
from pathlib import Path


def convert(ledger_path: Path, decision_path: Path, out_path: Path):
    days = {}
    with decision_path.open(newline="") as f:
        for r in csv.DictReader(f):
            days.setdefault(int(r["trt"]), []).append(
                (int(r["yrdoy"]), int(r["das"])))
    for trt in days:
        days[trt].sort(key=lambda x: x[1])

    fields = ["run", "trt", "yrdoy", "das", "layer"]
    rows_out = []
    run = 0
    with ledger_path.open(newline="") as f:
        reader = csv.DictReader(f)
        cols = [c for c in reader.fieldnames if c not in
                ("day_index", "layer")]
        fields += cols
        for r in reader:
            d = int(r["day_index"])
            if d == 1:
                run += 1
            trt = run
            if d > len(days.get(trt, [])):
                continue
            yrdoy, das = days[trt][d - 1]
            row = [run, trt, yrdoy, das, int(r["layer"])]
            row += [r[c] for c in cols]
            rows_out.append(row)
    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(fields)
        w.writerows(rows_out)
    print(f"converted {len(rows_out)} rows -> {out_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--decision", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    convert(Path(a.ledger), Path(a.decision), Path(a.out))


if __name__ == "__main__":
    main()
