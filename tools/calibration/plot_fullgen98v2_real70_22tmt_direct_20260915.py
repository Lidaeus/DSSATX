#!/usr/bin/env python3
"""22-treatment fit suite for full_gen98_v2 real70 via DIRECT replay
(mirrors the batch's own model command: run_dssat.py --batch --param-csv
--harvest-var CHPDT), then renders plot_dynamics."""
import json, os, re, shutil, subprocess, sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "workspace/runs/full_genetic_98pct_v2_20260915"
WORK = ROOT / "workspace/reports/fullgen98v2_real70_22tmt_20260915"
DET = WORK / "det_real70"
OUT = ROOT / "figture/full_gen98v2_real70_22tmt_full_suite_20260915"

def main():
    if WORK.exists():
        shutil.rmtree(WORK)
    DET.mkdir(parents=True)
    # params
    p = pd.read_csv(RUN / "full_gen98_v2_real70_parameters_fixed.csv")
    p = p.rename(columns={p.columns[0]: "name", "Value": "value"})
    p.to_csv(DET / "params.csv", index=False)
    # source inputs (batch-effective: Workspace root + iso 26SP)
    for src, dst in [
        (ROOT/"Workspace/XXQL2501.TMX", DET/"XXQL2501.TMX"),
        (ROOT/"Workspace/XXQL2501.TMA", DET/"XXQL2501.TMA"),
        (ROOT/"Workspace/XXQL2501.TMT", DET/"XXQL2501.TMT"),
        (ROOT/"data/user/experiments/XXQL2501/XXLI2502.WTH", DET/"XXLI2502.WTH"),
        (RUN/"_agents/agent_01/_iso_runs/run_1kch1mol/XXQL2601.TMX", DET/"XXQL2601.TMX"),
        (RUN/"_agents/agent_01/_iso_runs/run_1kch1mol/XXQL2601.TMA", DET/"XXQL2601.TMA"),
        (RUN/"_agents/agent_01/_iso_runs/run_1kch1mol/XXQL2601.TMT", DET/"XXQL2601.TMT"),
        (ROOT/"data/user/experiments/XXQL2601/XXQL2601.WTH", DET/"XXQL2601.WTH"),
    ]:
        shutil.copy2(src, dst)
    # 22-treatment batch
    lines = ["@FILEX                                                                                        TRTNO     RP     SQ     OP     CO",
             "$BATCH(TOMATO_CAL)", "!",
             "! full 22-treatment replay of full_gen98_v2 realization 70"]
    for tr in [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]:
        lines.append(f"XXQL2501 {tr:>4}     1     1     0     0")
    for tr in range(1, 13):
        lines.append(f"XXQL2601 {tr:>4}     1     1     0     0")
    (DET / "DSSBatch.v48").write_text("\r\n".join(lines) + "\r\n", encoding="utf-8", newline="")

    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    r = subprocess.run(
        [sys.executable, str(ROOT/"src/calibration/run_dssat.py"),
         "--param-csv", "params.csv", "--batch", "DSSBatch.v48", "--harvest-var", "CHPDT"],
        cwd=DET, capture_output=True, text=True, env=env)
    print("replay rc:", r.returncode)
    if r.returncode != 0:
        print("STDOUT tail:", r.stdout[-300:])
        print("STDERR tail:", r.stderr[-300:])
        raise SystemExit(1)
    n_p = len([f for f in DET.iterdir() if f.suffix == ".OUT"])
    print("OUT files:", sorted(f.name for f in DET.glob("Pest*.OUT")))

    # mapping
    sys.path.insert(0, str(ROOT))
    from src.calibration.nitrogen_response import derive_filex_water_n_mapping
    m25 = derive_filex_water_n_mapping(DET/"XXQL2501.TMX", season_id="25SP",
            treatments=[2,3,4,5,9,10,11,12,13,14])
    m26 = derive_filex_water_n_mapping(DET/"XXQL2601.TMX", season_id="26SP",
            treatments=list(range(1,13)))
    mcsv = DET/"water_n_mapping.csv"
    pd.concat([m25,m26], ignore_index=True).to_csv(mcsv, index=False, encoding="utf-8-sig")

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    pr = subprocess.run(
        [sys.executable, str(ROOT/"tools/calibration/plot_dynamics.py"),
         "--det-root", str(DET), "--out-root", str(OUT),
         "--seasons", "25SP,26SP", "--include-all-treatments",
         "--mapping-csv", str(mcsv)],
        cwd=ROOT, capture_output=True, text=True, env=env)
    print("plot rc:", pr.returncode)
    if pr.returncode != 0:
        print(pr.stdout[-600:], pr.stderr[-300:])
        raise SystemExit(1)
    print("figures:", sorted(p.name for p in OUT.rglob("*.png"))[:10], "...")


if __name__ == "__main__":
    main()
