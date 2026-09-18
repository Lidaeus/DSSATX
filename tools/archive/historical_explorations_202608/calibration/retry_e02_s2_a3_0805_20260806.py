"""Retry E02-S2 once with a different Sobol seed after a 3% transient model-failure draw."""
from __future__ import annotations
import os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = "e02_s2_harvest_terminal_morris_top95_a3_0805_100x3_20260806_retry2"
RUN = ROOT / "workspace/runs" / CASE
BUNDLE = ROOT / "data/user/experiments/xxql2501_corrected_management_layermean_20260806"
DESIGN = ROOT / "configs/runs/eggplant_e02_s1s2_morris_top95_plus_a3_0805_20260806.json"
MULTI = ROOT / "configs/runs/eggplant_e02_s1s2_a3_0805_multiseason_20260806.json"
POLICY = ROOT / "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260805.csv"
REP = ROOT / "workspace/runs/e02_s1_canopy_morris_top95_a3_0805_100x3_20260806/calibration_finalize/stage_representative_params.csv"
EXE = ROOT / "windows/windows_a3_20260805/dscsm048_a3.exe"
SPE = ROOT / "windows/windows_a3_20260805/Genotype/TMGRO048.SPE"
LOG = ROOT / "workspace/runs" / f"{CASE}.log"

def main() -> int:
    env = os.environ.copy(); env.update({"PYTHONPATH": str(ROOT), "DSSAT_CUSTOM_EXE": str(EXE), "DSSAT_SPE_BASE": str(SPE), "DSSAT_SOIL_BASE": str(BUNDLE/'SOIL.SOL'), "DSSAT_KEEP_RUNS": "1", "DSSAT_KEEP_FAILED_RUNS": "1"})
    RUN.mkdir(parents=True, exist_ok=True)
    with LOG.open("w", encoding="utf-8") as log:
        def call(cmd, cwd=ROOT):
            log.write("$ " + " ".join(map(str, cmd)) + "\n"); log.flush()
            p = subprocess.run(cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
            if p.returncode: raise SystemExit(p.returncode)
        call([sys.executable, str(ROOT/'src/calibration/build_pest.py'), '--mode','eggplant_stage2','--design-config',str(DESIGN),'--stage','S2','--multiseason-design',str(MULTI),'--input-dir',str(BUNDLE),'--bounds-id','eggplant_e02_s1s2_morris_top95_plus_a3_0805_v3_20260806','--bounds-crop','eggplant','--prefix',CASE,'--noptmax','3','--ies-num-reals','100','--random-seed','20260808','--initial-ensemble-method','sobol','--batch',str(BUNDLE/'DSSBatch.v48'),'--harvest-var','CHPDT','--include-n-uptake','--include-soil','--param-review-mode','off','--bounds-review-mode','off','--observation-policy-csv',str(POLICY),'--out-dir',str(RUN),'--weight-scheme','raw','--bad-phi-sigma','1e300','--fixed-from',str(REP)])
        call([sys.executable, str(ROOT/'src/calibration/run_multiseason.py'),'--design',str(MULTI),'--param-csv',str(RUN/f'{CASE}_params.csv'),'--harvest-var','CHPDT','--prefix',f'{CASE}_smoke','--keep-nitrogen-outputs'], cwd=RUN)
        call([sys.executable, str(ROOT/'tools/parallel/run_parallel.py'),'--run-dir',str(RUN),'--case',CASE,'--mode','ies','--n-agents','4','--port','4093','--wait'])
        call([sys.executable, str(ROOT/'tools/parallel/run_parallel.py'),'--run-dir',str(RUN),'--case',CASE,'--mode','ies','--finalize'])
    return 0

if __name__ == '__main__': raise SystemExit(main())
