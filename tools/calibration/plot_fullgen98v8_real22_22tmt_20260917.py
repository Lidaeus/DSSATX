#!/usr/bin/env python3
"""22-treatment diagnostic suite for full_gen98_v8 iter5_real22 (multi-season
balanced champion). Reuses the collaborator's verified replay environment and
the standard evaluate engine."""
from __future__ import annotations
import hashlib, json, os, re, shutil, subprocess, sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

RUN = ROOT / "workspace/runs/full_genetic_98pct_v8_20260917"
CAND = RUN / "cand_iter5_real22_calib"
PARAMS = RUN / "candidate_iter5_real22_params.csv"
WORK = ROOT / "workspace/reports/fullgen98v8_real22_22tmt_20260917"
DET = WORK / "det_engine"
OUT = ROOT / "figture/full_gen98v8_real22_22tmt_full_suite_20260917"

TRT_25 = [2,3,4,5,9,10,11,12,13,14]
TRT_26 = list(range(1,13))


def batch_line(filex: str, trtno: int) -> str:
    line = filex.ljust(97)
    line += str(trtno)
    line += " " * 6 + "1"
    line += " " * 6 + "0"
    line += " " * 6 + "0"
    line += " " * 6 + "0"
    return line


def run_22tmt() -> Path:
    """Direct DSSAT 22-treatment run using the verified candidate environment."""
    work = WORK / "det_direct"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(CAND, work)

    # 22-treatment batch
    lines = ["$BATCH(TOMATO_CAL)", "!", "! v8 real22 full 22-treatment diagnostic replay", "!",
             "@FILEX" + " "*88 + "TRTNO" + "     RP" + "     SQ" + "     OP" + "     CO"]
    for tr in TRT_25:
        lines.append(batch_line("XXQL2501.TMX", tr))
        lines.append("")
    for tr in TRT_26:
        lines.append(batch_line("XXQL2601.TMX", tr))
        lines.append("")
    (work / "DSSBatch.v48").write_text("\r\n".join(lines) + "\r\n", encoding="utf-8", newline="")

    # copy real22 params
    shutil.copy2(PARAMS, work / "params.csv")

    # inject real22 params into ECO
    p = pd.read_csv(PARAMS)
    params = dict(zip(p["name"].astype(str).str.lower(), pd.to_numeric(p["value"], errors="coerce")))
    eco = work / "TMGRO048.ECO"
    if eco.exists():
        elines = eco.read_text(encoding="utf-8-sig").splitlines(keepends=True)
        header = None
        for j, line in enumerate(elines):
            if line.strip().startswith("@ECO#"):
                header = line.split()
                header[0] = header[0].lstrip("@")
                continue
            if header and line.strip().startswith("TM0001"):
                spans = [(m.start(), m.end()) for m in re.finditer(r"\S+", line)]
                for k, hname in enumerate(header):
                    ln = hname.lower()
                    if ln in params and k < len(spans):
                        val = params[ln]
                        s, e = spans[k]
                        tok = "{:.6g}".format(val)
                        if len(tok) <= (e - s):
                            elines[j] = elines[j][:s] + tok.rjust(e - s) + elines[j][e:]
                        else:
                            elines[j] = elines[j][:s] + tok[:e-s] + elines[j][e:]
                break
        eco.write_text("".join(elines), encoding="utf-8", newline="")

    # fix DSSATPRO
    pro = work / "DSSATPRO.v48"
    if pro.exists():
        tx = pro.read_text(encoding="utf-8", errors="ignore")
        w = str(work)
        out = []
        for l in tx.splitlines(keepends=True):
            if l.strip().startswith(("CRD ", "TMD ")):
                out.append(l.strip().split()[0] + " " + w + "\n")
            else:
                out.append(l)
        pro.write_text("".join(out), encoding="utf-8")

    env = dict(os.environ)
    r = subprocess.run([str(work/"DSCSM048.EXE"), "B", "DSSBatch.v48"],
        cwd=work, capture_output=True, text=True, env=env, timeout=300)
    print("DSSAT rc:", r.returncode)
    if r.returncode != 0:
        print("err:", r.stdout[-300:] if r.stdout else r.stderr[-300:])
        raise SystemExit(1)

    runs = sum(1 for l in (work/"PlantGro.OUT").read_text(errors="ignore").splitlines()
               if re.match(r"\*RUN\s+\d+", l))
    print(f"PlantGro runs: {runs}")
    return work


def split_seasons(det_direct: Path):
    """Split outputs per season and generate compare CSVs + engine-format dirs."""
    from src.dssat.run_dssat import (
        _read_tmt_harvest_events, _read_tmt_process_points,
        _read_freshwt_var_by_run, _read_plantgro_vars_by_run)

    if DET.exists():
        shutil.rmtree(DET)
    DET.mkdir(parents=True)

    cf_all = _read_freshwt_var_by_run(str(det_direct/"FreshWt.OUT"), "CHFPW")
    cd_all = _read_freshwt_var_by_run(str(det_direct/"FreshWt.OUT"), "CHPDT")
    pg_all = _read_plantgro_vars_by_run(str(det_direct/"PlantGro.OUT"), ["LAID","LWAD","SWAD"])

    for season, excode, trts, start in [("25SP","XXQL2501",TRT_25,0), ("26SP","XXQL2601",TRT_26,10)]:
        sd = DET / "_seasons" / season
        sd.mkdir(parents=True)
        # copy inputs
        for f in det_direct.glob(f"{excode}.TM?"):
            shutil.copy2(f, sd / f.name)
        for f in det_direct.glob("*.WTH"):
            shutil.copy2(f, sd / f.name)
        for f in det_direct.glob("*.SOL"):
            shutil.copy2(f, sd / f.name)

        # split PlantGro/FreshWt: keep only this season's runs, renumber from 1
        for outname in ("PlantGro.OUT", "FreshWt.OUT"):
            src = det_direct / outname
            lines = src.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            out, new = [], 0
            for line in lines:
                m = re.match(r"\*RUN\s+(\d+)", line)
                if m:
                    rn = int(m.group(1))
                    if start + 1 <= rn <= start + len(trts):
                        new = rn - start
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
            rn = i + 1  # renumbered per season
            pg_r = pg.get(rn, {})
            cf_r = cf.get(rn, {})
            cd_r = cd.get(rn, {})
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
        pdf = pd.DataFrame(proc_rows)
        hdf = pd.DataFrame(harv_rows)
        hdf["HNO"] = hdf.groupby("TN").cumcount() + 1
        pdf.to_csv(sd / f"{season}_deterministic_process_compare.csv", index=False, encoding="utf-8-sig")
        hdf.to_csv(sd / f"{season}_deterministic_harvest_compare.csv", index=False, encoding="utf-8-sig")
        print(f"{season}: {len(proc_rows)} proc, {len(harv_rows)} harv")

        # minimal manifest
        files = [{"name": q.name, "sha256": hashlib.sha256(q.read_bytes()).hexdigest(),
                  "bytes": q.stat().st_size} for q in sorted(sd.iterdir()) if q.is_file()]
        (sd / "input_manifest.json").write_text(
            json.dumps({"bundle_id": f"v8_real22_replay_{season}", "files": files}, indent=2) + "\n",
            encoding="utf-8")

    shutil.copy2(PARAMS, DET / "best_member_22_params.csv")
    (DET / "multiseason_run_status.json").write_text(
        json.dumps({"status": "done"}), encoding="utf-8")


def run_engine():
    import tools.calibration.evaluate_fixedsoil_official_best189_20260813 as evaluation
    from src.calibration.nitrogen_response import derive_filex_water_n_mapping

    m25 = derive_filex_water_n_mapping(DET/"_seasons/25SP/XXQL2501.TMX", season_id="25SP", treatments=TRT_25)
    m26 = derive_filex_water_n_mapping(DET/"_seasons/26SP/XXQL2601.TMX", season_id="26SP", treatments=TRT_26)
    mapping = DET / "two_season_water_n_mapping.csv"
    pd.concat([m25, m26], ignore_index=True).to_csv(mapping, index=False, encoding="utf-8-sig")

    evaluation.RUN_DIR = RUN
    evaluation.DET_ROOT = DET
    evaluation.OUT_ROOT = OUT
    evaluation.FIGURE = ROOT / "figture"
    evaluation.CASE = "full_gen98_v8"
    evaluation.BEST_MEMBER = "22"
    evaluation.SOURCE_ITERATION = 5
    evaluation.BEST_PHI = 0  # unknown; placeholder
    evaluation.CALIBRATION_STATE = "completed_engineering_validated"
    evaluation.ARTIFACT_TYPE = "two_season_diagnostics_fullgen98v8_real22_20260917"
    evaluation.SPE = ROOT / "data/templates/genotype/TMGRO048.SPE.base"
    evaluation.HARVEST_OBJECTIVE = "v8 multi-season balanced champion (164 params)"
    evaluation.SOIL_INJECTION_DESCRIPTION = "per v8 batch"
    evaluation.OBS_REGISTRY = RUN / "nonexistent_registry.csv"  # safe Path
    evaluation.PLOT_INCLUDE_ALL_TREATMENTS = True
    evaluation.PLOT_MAPPING_CSV = mapping
    evaluation.SEASONS = [
        {"season_id": "25SP", "excode": "XXQL2501", "treatments": TRT_25,
         "bundle": DET / "_seasons/25SP"},
        {"season_id": "26SP", "excode": "XXQL2601", "treatments": TRT_26,
         "bundle": DET / "_seasons/26SP"}]
    evaluation.SEASON_IDS = ["25SP", "26SP"]
    evaluation.COLORS = {"25SP": "#2878B5", "26SP": "#2A9D55"}
    evaluation.EXTRA_LIMITATIONS = [
        "V8 multi-season balanced champion: iter5_real22 (164 active parameters).",
        "Diagnostic suite only; posterior/uncertainty figures excluded per user request.",
    ]
    evaluation._swap = lambda: []
    evaluation._restore = lambda replacements: None
    evaluation.EXE = ROOT / "DSCSM048.EXE"
    os.environ["DSSAT_CUSTOM_EXE"] = str(evaluation.EXE.resolve())
    os.environ["DSSAT_SPE_BASE"] = str(evaluation.SPE.resolve())
    os.environ["PYTHONPATH"] = str(ROOT)

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    result = int(evaluation.main() or 0)

    mp = OUT / "diagnostic_manifest.json"
    if mp.is_file():
        m = json.loads(mp.read_text(encoding="utf-8"))
        m.update(
            member_selection_rule="V8 multi-season balanced champion (user-selected iter5_real22)",
            custom_genetic_params="real22 parameters (164 params, direct ECO injection)",
            bundle_note="cand_iter5_real22_calib environment (collaborator-verified)")
        mp.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    det = run_22tmt()
    split_seasons(det)
    return run_engine()


if __name__ == "__main__":
    raise SystemExit(main())
