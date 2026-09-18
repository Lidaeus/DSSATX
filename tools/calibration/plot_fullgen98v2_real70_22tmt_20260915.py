#!/usr/bin/env python3
"""22-treatment fit-capability suite for full_genetic_98pct_v2 realization 70
(Pareto-optimal member, user-selected 2026-09-15). Replays via per-season
multiseason designs on mini-bundles assembled from the batch's effective
inputs, then renders the canonical plot_dynamics suite."""
import json, shutil, subprocess, sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.calibration.nitrogen_response import derive_filex_water_n_mapping

RUN = ROOT / "workspace/runs/full_genetic_98pct_v2_20260915"
ISO = RUN / "_agents/agent_01/_iso_runs/run_1kch1mol"
WS = ROOT / "Workspace"
WORK = ROOT / "workspace/reports/full_gen98v2_real70_22tmt_20260915"
DET = WORK / "det_real70"
OUT = ROOT / "figture/full_gen98v2_real70_22tmt_full_suite_20260915"
OBS = ROOT / "configs/runs/e02_formal_v47_free_nscale_observation_policy_20260901.csv"
GRP = ROOT / "configs/runs/e02_formal_v48_n_gradient_water2x_group_policy_20260902.csv"

B25 = WORK / "bundle_25sp"
B26 = WORK / "bundle_26sp"


def assemble():
    if WORK.exists():
        shutil.rmtree(WORK)
    for b, srcs in [(B25, [WS/"XXQL2501.TMX", WS/"XXQL2501.TMA", WS/"XXQL2501.TMT",
                           ROOT/"data/user/experiments/XXQL2501/XXLI2502.WTH",
                           ROOT/"data/raw/soil/SOIL.SOL",
                           ROOT/"data/templates/batch/DSSBatch.v48"]),
                    (B26, [ISO/"XXQL2601.TMX", ISO/"XXQL2601.TMA", ISO/"XXQL2601.TMT",
                           ROOT/"data/user/experiments/XXQL2601/XXQL2601.WTH",
                           ROOT/"data/raw/soil/SOIL.SOL",
                           ROOT/"data/templates/batch/DSSBatch.v48"])]:
        b.mkdir(parents=True)
        for s in srcs:
            shutil.copy2(s, b / s.name)
    # params: real70 fixed export -> name,value
    p = pd.read_csv(RUN / "full_gen98_v2_real70_parameters_fixed.csv")
    p = p.rename(columns={p.columns[0]: "name", "Value": "value"})
    DET.mkdir(parents=True)
    p.to_csv(DET / "params.csv", index=False)
    # per-season full-treatment batch files
    for b, ex, trts in [(B25, "XXQL2501", [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]),
                        (B26, "XXQL2601", list(range(1, 13)))]:
        lines = ["@FILEX                                                                                        TRTNO     RP     SQ     OP     CO",
                 "$BATCH(TOMATO_CAL)", "!",
                 "! full 22-treatment replay of full_gen98_v2 realization 70", "!"]
        for tr in trts:
            lines.append(f"{ex} {tr:>4}     1     1     0     0")
        (b / "DSSBatch.v48").write_text(
            chr(13) + chr(10).join([""]) + chr(13) + chr(10).join(lines) + chr(13) + chr(10),
            encoding="utf-8", newline="")
    # minimal manifests (loader requires one)
    import hashlib
    for b, sid in [(B25, "25SP"), (B26, "26SP")]:
        files = [{"name": q.name, "sha256": hashlib.sha256(q.read_bytes()).hexdigest(),
                  "bytes": q.stat().st_size} for q in sorted(b.iterdir()) if q.is_file()]
        (b / "input_manifest.json").write_text(json.dumps(
            {"bundle_id": b.name, "season": sid,
             "purpose": "fullgen98v2 real70 22-tmt replay inputs", "files": files},
            ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(p)


def design(season, excode, bundle, treatments):
    d = {"schema_version": 1, "status": "approved_for_execution",
         "design_id": f"fullgen98_real70_replay_{season}_20260915",
         "cultivar_identity": "TM0008",
         "purpose": f"22-tmt suite replay of full_gen98_v2 realization 70 ({season})",
         "observation_policy": str(OBS.relative_to(ROOT)).replace("\\", "/"),
         "group_policy": str(GRP.relative_to(ROOT)).replace("\\", "/"),
         "bounds_id": "eggplant_full_genetic_98pct_v2_20260915",
         "diagnostic_single_season": True,
         "seasons": [{"season_id": season, "experiment_code": excode,
                      "bundle_path": str(bundle.relative_to(ROOT)).replace("\\", "/"),
                      "role": "calibration", "treatments": treatments}]}
    p = WORK / f"design_{season}.json"
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def run_season(season, excode, bundle, treatments):
    dsn = design(season, excode, bundle, treatments)
    cwd = DET / season
    shutil.rmtree(cwd, ignore_errors=True)
    cwd.mkdir(parents=True)
    r = subprocess.run([sys.executable, str(ROOT/"src/calibration/run_multiseason.py"),
                        "--design", str(dsn.resolve()), "--param-csv", str((DET/"params.csv").resolve()),
                        "--prefix", f"r70_{season}", "--harvest-var", "CHFPW"],
                       cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        print(r.stdout[-800:], r.stderr[-400:])
        raise SystemExit(f"replay failed: {season}")
    print(season, "replay OK")


def main():
    n = assemble()
    print("params:", n)
    run_season("25SP", "XXQL2501", B25, [2, 3, 4, 5, 9, 10, 11, 12, 13, 14])
    run_season("26SP", "XXQL2601", B26, list(range(1, 13)))
    # mapping
    maps = [derive_filex_water_n_mapping(b / f"{e}.TMX", season_id=s,
             treatments=( [2,3,4,5,9,10,11,12,13,14] if s=="25SP" else list(range(1,13))))
            for s, e, b in [("25SP","XXQL2501",B25), ("26SP","XXQL2601",B26)]]
    mcsv = DET / "water_n_mapping.csv"
    pd.concat(maps, ignore_index=True).to_csv(mcsv, index=False, encoding="utf-8-sig")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    env_path = WORK / "run_env.py"
    r = subprocess.run([sys.executable, str(ROOT/"tools/calibration/plot_dynamics.py"),
                        "--det-root", str(DET), "--out-root", str(OUT),
                        "--seasons", "25SP,26SP", "--include-all-treatments",
                        "--mapping-csv", str(mcsv)],
                       cwd=ROOT, capture_output=True, text=True,
                       env={**__import__("os").environ, "PYTHONPATH": str(ROOT)})
    print("plot rc:", r.returncode)
    if r.returncode:
        print(r.stdout[-1000:], r.stderr[-500:])
        raise SystemExit(1)
    print("figures:", sorted(p.name for p in OUT.rglob("*.png"))[:8], "...")


if __name__ == "__main__":
    main()
