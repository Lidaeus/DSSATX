#!/usr/bin/env python3
"""Three-season (25SP+26SP+25FA) 34-treatment diagnostic suite for
full_gen98_v7 iter5_real77. Reuses collaborator-verified environments."""
from __future__ import annotations
import hashlib, json, os, re, shutil, subprocess, sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

RUN = ROOT / "workspace/runs/full_genetic_98pct_v7_20260917"
CALIB = RUN / "cand_iter5_real77_calib"     # has XXQL2501 + XXQL2601
FA = RUN / "cand_iter5_real77_25fa"          # has XXQL2502
PARAMS = RUN / "candidate_iter5_real77_params.csv"
WORK = ROOT / "workspace/reports/fullgen98v7_real77_3season_20260917"
DET = WORK / "det_engine"
OUT = ROOT / "figture/full_gen98v7_real77_3season_full_suite_20260917"

TRT_25 = [2,3,4,5,9,10,11,12,13,14]
TRT_26 = list(range(1,13))
TRT_FA = list(range(1,13))
SEASON_DEFS = [
    ("25SP", "XXQL2501", TRT_25),
    ("26SP", "XXQL2601", TRT_26),
    ("25FA", "XXQL2502", TRT_FA),
]


def batch_line(filex: str, trtno: int) -> str:
    line = filex.ljust(97) + str(trtno)
    for _ in range(4):
        line += " " * 6 + ("1" if _ == 0 else "0")
    return line


def run_34tmt() -> Path:
    work = WORK / "det_direct"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(CALIB, work)
    # bring in 25FA FileX + weather from the FA environment
    for f in FA.glob("XXQL2502.*"):
        shutil.copy2(f, work / f.name)
    # ensure 25FA weather is available
    if not (work / "XXLI2502.WTH").exists():
        src = ROOT / "data/user/experiments/XXQL2502/XXLI2502.WTH"
        if src.exists():
            shutil.copy2(src, work / "XXLI2502.WTH")

    # 34-treatment batch
    lines = ["$BATCH(TOMATO_CAL)", "!", "! v7 real77 three-season full diagnostic replay", "!",
             "@FILEX" + " "*88 + "TRTNO" + "     RP" + "     SQ" + "     OP" + "     CO"]
    for _, ex, trts in SEASON_DEFS:
        for tr in trts:
            lines.append(batch_line(f"{ex}.TMX", tr))
            lines.append("")
    (work / "DSSBatch.v48").write_text("\r\n".join(lines) + "\r\n", encoding="utf-8", newline="")

    # inject real77 into ECO
    p = pd.read_csv(PARAMS)
    params = dict(zip(p["name"].astype(str).str.lower(), pd.to_numeric(p["value"], errors="coerce")))
    eco = work / "TMGRO048.ECO"
    elines = eco.read_text(encoding="utf-8-sig").splitlines(keepends=True)
    header = None
    for j, line in enumerate(elines):
        if line.strip().startswith("@ECO#"):
            header = line.split(); header[0] = header[0].lstrip("@"); continue
        if header and line.strip().startswith("TM0001"):
            spans = [(m.start(), m.end()) for m in re.finditer(r"\S+", line)]
            for k, h in enumerate(header):
                ln = h.lower()
                if ln in params and k < len(spans):
                    s, e = spans[k]
                    tok = "{:.6g}".format(params[ln])
                    elines[j] = elines[j][:s] + (tok.rjust(e-s) if len(tok) <= e-s else tok[:e-s]) + elines[j][e:]
            break
    eco.write_text("".join(elines), encoding="utf-8", newline="")

    # DSSATPRO
    pro = work / "DSSATPRO.v48"
    tx = pro.read_text(encoding="utf-8", errors="ignore")
    w = str(work)
    pro.write_text("".join(
        (l.strip().split()[0] + " " + w + "\n") if l.strip().startswith(("CRD ","TMD ")) else l
        for l in tx.splitlines(keepends=True)), encoding="utf-8")

    r = subprocess.run([str(work/"DSCSM048.EXE"), "B", "DSSBatch.v48"],
        cwd=work, capture_output=True, text=True, env=dict(os.environ), timeout=600)
    print("DSSAT rc:", r.returncode)
    if r.returncode != 0:
        print((r.stdout or r.stderr)[-300:])
        raise SystemExit(1)
    runs = sum(1 for l in (work/"PlantGro.OUT").read_text(errors="ignore").splitlines()
               if re.match(r"\*RUN\s+\d+", l))
    print(f"PlantGro: {runs} runs")
    return work


def build_engine(det_direct: Path):
    from src.dssat.run_dssat import (
        _read_tmt_harvest_events, _read_tmt_process_points,
        _read_freshwt_var_by_run, _read_plantgro_vars_by_run)

    if DET.exists():
        shutil.rmtree(DET)
    DET.mkdir(parents=True)

    for season, excode, trts in SEASON_DEFS:
        sd = DET / "_seasons" / season
        sd.mkdir(parents=True)
        for f in det_direct.glob(f"{excode}.TM?"):
            shutil.copy2(f, sd / f.name)
        for f in det_direct.glob("*.WTH"):
            shutil.copy2(f, sd / f.name)
        for f in det_direct.glob("*.SOL"):
            shutil.copy2(f, sd / f.name)

        # split PlantGro/FreshWt per season
        start_run = sum(len(t) for _, _, t in SEASON_DEFS[:SEASON_DEFS.index((season, excode, trts))])
        n = len(trts)
        for outname in ("PlantGro.OUT", "FreshWt.OUT"):
            src = det_direct / outname
            lines = src.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            out, new = [], 0
            for line in lines:
                m = re.match(r"\*RUN\s+(\d+)", line)
                if m:
                    rn = int(m.group(1))
                    if start_run + 1 <= rn <= start_run + n:
                        new = rn - start_run
                        out.append(re.sub(r"\*RUN\s+\d+", f"*RUN  {new:04d}", line))
                    else:
                        new = 0
                    continue
                if new > 0:
                    out.append(line)
            (sd / outname).write_text("".join(out), encoding="utf-8")

        # compare CSVs
        events = _read_tmt_harvest_events(str(sd / f"{excode}.TMT"))
        points = _read_tmt_process_points(str(sd / f"{excode}.TMT"))
        pg = _read_plantgro_vars_by_run(str(sd/"PlantGro.OUT"), ["LAID","LWAD","SWAD"])
        cf = _read_freshwt_var_by_run(str(sd/"FreshWt.OUT"), "CHFPW")
        cd = _read_freshwt_var_by_run(str(sd/"FreshWt.OUT"), "CHPDT")

        proc_rows, harv_rows = [], []
        for i, tn in enumerate(trts):
            rn = i + 1
            pg_r = pg.get(rn, {}); cf_r = cf.get(rn, {}); cd_r = cd.get(rn, {})
            for pt in points.get(tn, []):
                d = str(int(pt["date"]))
                proc_rows.append({"RUN": rn, "TN": tn, "DATE": int(pt["date"]),
                    "OBS_LAID": float(pt.get("laid",-99)), "SIM_LAID": pg_r.get(d,{}).get("LAID",-99),
                    "OBS_LWAD": float(pt.get("lwad",-99)), "SIM_LWAD": pg_r.get(d,{}).get("LWAD",-99),
                    "OBS_SWAD": float(pt.get("swad",-99)), "SIM_SWAD": pg_r.get(d,{}).get("SWAD",-99)})
            sorted_d = sorted(cf_r.keys())
            prev_cf, prev_cd = 0.0, 0.0
            for d in sorted_d:
                for ev in events.get(tn, []):
                    if int(ev["date"]) == d:
                        cfv = cf_r[d]; cdv = cd_r.get(d, -99)
                        harv_rows.append({"RUN": rn, "TN": tn, "DATE": d,
                            "OBS_FRESH_CUM": float(ev.get("fresh_cum",-99)), "SIM_FRESH_CUM": cfv,
                            "OBS_FRESH_INC": float(ev.get("fresh_inc",-99)), "SIM_FRESH_INC": cfv - prev_cf,
                            "OBS_DRY_CUM": float(ev.get("dry_cum",-99)), "SIM_DRY_CUM": cdv,
                            "OBS_DRY_INC": float(ev.get("dry_inc",-99)), "SIM_DRY_INC": cdv - prev_cd if cdv > 0 else -99})
                prev_cf = cf_r[d]
                if d in cd_r and cd_r[d] > 0:
                    prev_cd = cd_r[d]
        pdf = pd.DataFrame(proc_rows); hdf = pd.DataFrame(harv_rows)
        hdf["HNO"] = hdf.groupby("TN").cumcount() + 1 if len(hdf) else []
        pdf.to_csv(sd / f"{season}_deterministic_process_compare.csv", index=False, encoding="utf-8-sig")
        if len(hdf):
            hdf.to_csv(sd / f"{season}_deterministic_harvest_compare.csv", index=False, encoding="utf-8-sig")
        print(f"{season}: {len(proc_rows)} proc, {len(hdf)} harv")

        files = [{"name": q.name, "sha256": hashlib.sha256(q.read_bytes()).hexdigest(),
                  "bytes": q.stat().st_size} for q in sorted(sd.iterdir()) if q.is_file()]
        (sd / "input_manifest.json").write_text(
            json.dumps({"bundle_id": f"v7_real77_replay_{season}", "files": files}, indent=2) + "\n",
            encoding="utf-8")

    shutil.copy2(PARAMS, DET / "best_member_77_params.csv")
    (DET / "multiseason_run_status.json").write_text(json.dumps({"status": "done"}), encoding="utf-8")


def run_engine():
    import tools.calibration.evaluate_fixedsoil_official_best189_20260813 as evaluation
    from src.calibration.nitrogen_response import derive_filex_water_n_mapping

    maps = []
    for season, excode, trts in SEASON_DEFS:
        m = derive_filex_water_n_mapping(DET/f"_seasons/{season}/{excode}.TMX",
                                         season_id=season, treatments=trts)
        maps.append(m)
    mapping = DET / "three_season_water_n_mapping.csv"
    pd.concat(maps, ignore_index=True).to_csv(mapping, index=False, encoding="utf-8-sig")

    evaluation.RUN_DIR = RUN
    evaluation.DET_ROOT = DET
    evaluation.OUT_ROOT = OUT
    evaluation.FIGURE = ROOT / "figture"
    evaluation.CASE = "full_gen98_v7"
    evaluation.BEST_MEMBER = "77"
    evaluation.SOURCE_ITERATION = 5
    evaluation.BEST_PHI = 0
    evaluation.CALIBRATION_STATE = "completed_engineering_validated"
    evaluation.ARTIFACT_TYPE = "three_season_diagnostics_fullgen98v7_real77_20260917"
    evaluation.SPE = ROOT / "data/templates/genotype/TMGRO048.SPE.base"
    evaluation.HARVEST_OBJECTIVE = "v7 champion (164 params, three-season)"
    evaluation.SOIL_INJECTION_DESCRIPTION = "per v7 batch"
    evaluation.OBS_REGISTRY = RUN / "nonexistent.csv"
    evaluation.PLOT_INCLUDE_ALL_TREATMENTS = True
    evaluation.PLOT_MAPPING_CSV = mapping
    evaluation.SEASONS = [
        {"season_id": s, "excode": ex, "treatments": trts, "bundle": DET / f"_seasons/{s}"}
        for s, ex, trts in SEASON_DEFS]
    evaluation.SEASON_IDS = [s for s, _, _ in SEASON_DEFS]
    evaluation.COLORS = {"25SP": "#2878B5", "26SP": "#2A9D55", "25FA": "#E67E22"}
    evaluation.EXTRA_LIMITATIONS = [
        "V7 champion: iter5_real77 (164 params). Three-season replay: 25SP(10) + 26SP(12) + 25FA(12) = 34 treatments.",
        "25FA is a cross-season migration check (not used in calibration); results are diagnostic only.",
        "Diagnostic suite only; posterior/uncertainty figures excluded.",
    ]
    evaluation._swap = lambda: []
    evaluation._restore = lambda r: None
    evaluation.EXE = ROOT / "DSCSM048.EXE"
    os.environ["DSSAT_CUSTOM_EXE"] = str(evaluation.EXE.resolve())
    os.environ["DSSAT_SPE_BASE"] = str(evaluation.SPE.resolve())
    os.environ["PYTHONPATH"] = str(ROOT)

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    return int(evaluation.main() or 0)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    det = run_34tmt()
    build_engine(det)
    return run_engine()


if __name__ == "__main__":
    raise SystemExit(main())
