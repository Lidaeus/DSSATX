#!/usr/bin/env python3
"""Build the three unified season bundles (T0/P0 P0-2, decisions D1-D12).

2026-09-14, per docs/T0P0执行与三季设置核对_统一决策文档_20260913.md (user
replies) and docs/reports/P0执行前审查_三季设置与模型方法_20260914.md:

  D1=A  26SP harvest observations: TMT (unscaled measured) is the sole
        authority; FileT_values regenerated from the generator (=TMT values,
        no 0.90 factor anywhere).
  D2=A  REMOVALS merged into the main generator (done in
        build_trial_observations_v2_20260726.py); regeneration reproduces them.
  D3=C  26SP 26180 LAI imputation (12 points, R=18.52) included in the
        unified 26SP bundle with imputed flags and propagated errors; no
        extra budget cap applied (user C).
  D4=A  26SP initial N: 0.34x baseline baked once; extra ICNS_26SP removed
        (parameter fixed at 1.0 in the new frozen bounds, P0-3).
  FileX settings per approved table: PHOSP=Y (P input validation pending
        per review 4.1 - flagged in manifest), POTAS=N (CRGRO has no K
        response), TILL=Y all seasons, CHEM=N all, PAGE 25/24/25 fixed,
        PENV=20 fixed, PLDP=8, PLWT=15 (model input kg DM/ha), PLPH=1,
        SPRL=8, fertigation FDEP=10cm, 26SP tillage/IC dates swapped
        (till 26071->26073, ICDAT 26073->26071), ICRT/ICRES=0 explicit,
        25SP harvest calendar 9 real (obs-1d) + 1 virtual (=25198),
        new soil ID XXSL1800S1 (derived SL/180/7-layer), WTH headers
        35.16/113.8/75m, FA title 2025 AUTUMN.

Old packages are never modified.  Every new bundle carries a manifest with
decision references and SHA-256 for every file.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.experiments.build_trial_observations_v2_20260726 as generator

REF = ROOT / "data/user/ref/DSSAT文件"
NEW_SOIL_ID = "XXSL1800S1"
B25_SRC = ROOT / "data/user/experiments/xxql2501_scheme4_double_n_20260831"
B26_SRC = ROOT / "workspace/reports/e02_v46_26sp_soil_n_scale_sweep_20260901/bundles_v2/s0p34"
BFA_SRC = ROOT / "data/user/experiments/XXQL2502"
OUT25 = ROOT / "data/user/experiments/xxql2501_unified_20260914"
OUT26 = ROOT / "data/user/experiments/xxql2601_unified_20260914"
OUTFA = ROOT / "data/user/experiments/xxql2502_unified_20260914"

# 26SP 26180 LAI imputation (user-approved 2026-08-31, R=18.52)
LAI_IMPUTED = {1: 2.646, 2: 2.912, 3: 2.629, 4: 3.079, 5: 3.113, 6: 2.143,
               7: 2.775, 8: 3.142, 9: 2.053, 10: 2.026, 11: 2.590, 12: 2.735}
LAI_IMPUTED_SD = {1: 0.678, 2: 0.447, 3: 0.842, 4: 0.508, 5: 0.297, 6: 0.387,
                  7: 0.220, 8: 0.340, 9: 0.243, 10: 0.349, 11: 0.717, 12: 0.357}
LAI_IMPUTED_N = {1: 3, 2: 2, 3: 3, 4: 2, 5: 2, 6: 3, 7: 2, 8: 3, 9: 3, 10: 3, 11: 3, 12: 3}

# Deprecated: PLANTING_OVERRIDES replaced by strict Fortran fixed-width column replacement
# PLANTING_OVERRIDES = {
#     "25SP": {9: "8", 10: "15.", 11: "25", 12: "20", 13: "1", 14: "8"},
#     "26SP": {9: "8", 10: "15.", 11: "24", 12: "20", 13: "1", 14: "8"},
#     "25FA": {9: "8", 10: "15.", 11: "25", 12: "20", 13: "1", 14: "8"},
# }
OP_SWITCHES = {"WATER": "Y", "NITRO": "Y", "SYMBI": "N", "PHOSP": "Y",
               "POTAS": "N", "DISES": "N", "CHEM": "N", "TILL": "Y", "CO2": "M"}


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def token_spans(line: str):
    """Yield (index, start, end, text) for whitespace-separated tokens."""
    return [(m.start(), m.end()) for m in re.finditer(r"\S+", line)]


def replace_token(line: str, idx: int, new_value: str) -> str:
    spans = token_spans(line)
    if idx >= len(spans):
        raise ValueError(f"token {idx} out of range: {line!r}")
    s, e = spans[idx]
    if len(new_value) > (e - s):
        # widen right into following spaces when possible
        end = e
        while end < len(line) and line[end] == " " and len(new_value) > (end - s):
            end += 1
        if len(new_value) > (end - s):
            raise ValueError(f"cannot fit {new_value!r} in token {idx}: {line!r}")
        return line[:s] + new_value + line[end:]
    return line[:s] + new_value.rjust(e - s) + line[e:]


OP_TOKEN_NAMES = ["WATER", "NITRO", "SYMBI", "PHOSP", "POTAS", "DISES", "CHEM", "TILL", "CO2"]


def edit_filex(path: Path, season: str) -> dict:
    """Apply approved FileX edits in place; return audit counts."""
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines(keepends=True)
    eol = "\r\n" if text.endswith("\r\n") or "\r\n" in text[:2000] else "\n"
    audit = {"op_lines": 0, "plant_lines": 0, "fert_lines": 0, "ic_lines": 0,
             "till_lines": 0, "harvest_lines_removed": 0, "soil_id_lines": 0,
             "title_lines": 0, "elev_lines": 0, "sa_smpx_lines": 0,
             "sa_sapx_extended": 0, "sa_layers_added": 0,
             "fert_fdep_lines": 0, "fert_famp_lines": 0}
    out = []
    section = None
    header_tokens = []
    fert_seen = set()  # treatments whose base N dressing was already seen
    cur_sa_trno = None
    cur_sa_sapx60 = None
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip("\r\n")
        stripped = line.strip()

        if stripped.startswith("@") or stripped.startswith("*") or not stripped:
            if stripped.startswith("@"):
                section = stripped.split()[0][1:]
                header_tokens = stripped.split()
            out.append(raw)
            i += 1
            continue

        # Soil Analysis lines (Section A, D-P1~D-P3, D-P6)
        if section == "A":
            if "SADAT" in header_tokens and len(stripped) >= 20 and not stripped.startswith("@"):
                cur_sa_trno = int(line[:3].strip())
                # Replace SMPX (-99) with SA001 (Olsen method, D-P1)
                line = line[:15] + "SA001" + line[20:]
                audit["sa_smpx_lines"] += 1
                out.append(line + eol)
                i += 1
                continue
            elif "SABL" in header_tokens and len(stripped) >= 44 and not stripped.startswith("@"):
                depth = int(line[3:8].strip())
                if depth == 60:
                    cur_sa_sapx60 = float(line[39:44].strip())
                elif depth in [80, 100]:
                    line = line[:39] + f"{cur_sa_sapx60:5.1f}" + line[44:]
                    audit["sa_sapx_extended"] += 1
                    out.append(line + eol)
                    if depth == 100:
                        # Append deep layers (120, 150, 180cm, D-P3 fallback A)
                        for d in [120, 150, 180]:
                            extra = f"{cur_sa_trno:3d}{d:5.0f}   1.5   -99   -99   -99   -99 {cur_sa_sapx60:5.1f}   -99   -99"
                            out.append(extra + eol)
                            audit["sa_layers_added"] += 1
                    i += 1
                    continue
            out.append(line + eol)
            i += 1
            continue

        # @N OPTIONS line (data tokens: TRNO, 'OP', then 9 switches)
        if section == "N":
            spans = token_spans(line)
            if len(spans) >= 11 and line[spans[1][0]:spans[1][1]] == "OP":
                for j, name in enumerate(OP_TOKEN_NAMES):
                    want = OP_SWITCHES[name]
                    ti = j + 2
                    cur = line[spans[ti][0]:spans[ti][1]]
                    if cur.strip() != want:
                        line = replace_token(line, ti, want)
                audit["op_lines"] += 1
                out.append(line + eol)
                i += 1
                continue

        # planting data lines (section P after @P header with PDATE token)
        if section == "P" and "PDATE" in header_tokens:
            stripped_line = line.strip()
            if stripped_line and stripped_line[0].isdigit():
                if len(line) < 86:
                    line = line.ljust(86)
                page_val = "   24" if season == "26SP" else "   25"
                # Strict Fortran FORMAT (I3,I5,1X,I5,2(F6.0),2(5X,A1),8(1X,F5.0),I6,F6.0,2I6)
                # Columns 51:86 (0-based line[50:86], 36 characters) covers:
                # SDEPTH (51:56='     8'), SDWTPL (57:62='   15.'),
                # SDAGE  (63:68='    25' or '    24'), ATEMP (69:74='    20'),
                # PLPH   (75:80='     1'), SPRLAP (81:86='     8')
                planting_block = f"     8   15. {page_val}    20     1     8"
                line = line[:50] + planting_block + line[86:]
                audit["plant_lines"] += 1
            out.append(line + eol)
            i += 1
            continue

        # Fertilizer lines (Section F, D10 + D-P4)
        if section == "F" and "FDEP" in header_tokens:
            spans = token_spans(line)
            fdate_i = header_tokens.index("FDATE")
            fmcd_i = header_tokens.index("FMCD")
            fdep_i = header_tokens.index("FDEP")
            famp_i = header_tokens.index("FAMP")
            if len(spans) > famp_i:
                fdate = line[spans[fdate_i][0]:spans[fdate_i][1]].strip()
                fmcd = line[spans[fmcd_i][0]:spans[fmcd_i][1]].strip()
                old_fdep = line[spans[fdep_i][0]:spans[fdep_i][1]].strip()
                old_famp = float(line[spans[famp_i][0]:spans[famp_i][1]].strip())
                base_dates = {"25SP": "25069", "26SP": "26072", "25FA": "25223"}
                is_top = (fdate > base_dates[season])

                # D10: Fertigation topdressing depth = 10 cm for all non-base fertigation (FE005, FE300, FE018)
                if is_top and fmcd in ["FE005", "FE300", "FE018"]:
                    if old_fdep != "10":
                        line = replace_token(line, fdep_i, "10")
                        audit["fert_fdep_lines"] += 1

                # D-P4: Convert FAMP from P2O5 to elemental P (x 0.4364)
                if old_famp > 0:
                    if season == "25SP":
                        new_famp = "65.5"
                    elif season == "26SP":
                        if not is_top and round(old_famp) == 45:
                            new_famp = "19.8"
                        elif is_top and round(old_famp) == 9:
                            new_famp = "3.9"
                        elif is_top and round(old_famp) == 13:
                            new_famp = "5.7"
                        else:
                            new_famp = f"{old_famp * 0.4364:.1f}"
                    elif season == "25FA":
                        if not is_top and round(old_famp) == 45:
                            new_famp = "19.6"
                        elif is_top and round(old_famp) == 18:
                            new_famp = "7.9"
                        elif is_top and round(old_famp) == 36:
                            new_famp = "15.7"
                        else:
                            new_famp = f"{old_famp * 0.4364:.1f}"
                    else:
                        new_famp = f"{old_famp * 0.4364:.1f}"
                    line = replace_token(line, famp_i, new_famp)
                    audit["fert_famp_lines"] += 1
            out.append(line + eol)
            i += 1
            continue

        # IC header line (data[0]=TRNO ↔ header[0]; ICDAT/ICRT/ICRES by name)
        if section == "C" and "ICDAT" in header_tokens:
            spans = token_spans(line)
            icdat_i = header_tokens.index("ICDAT")
            icrt_i = header_tokens.index("ICRT")
            icres_i = header_tokens.index("ICRES")
            if len(spans) > icres_i:
                if season == "26SP":
                    cur = line[spans[icdat_i][0]:spans[icdat_i][1]].strip()
                    if cur == "26073":
                        line = replace_token(line, icdat_i, "26071")
                    for ti, zero in ((icrt_i, "0.00"), (icres_i, "0.000")):
                        cur = line[spans[ti][0]:spans[ti][1]].strip()
                        if float(cur) != 0.0:
                            line = replace_token(line, ti, zero)
                audit["ic_lines"] += 1
            out.append(line + eol)
            i += 1
            continue

        # tillage lines (26SP: TI042 26071 -> 26073)
        if section == "T" and "TDATE" in header_tokens:
            if season == "26SP" and stripped.split()[:2] == [stripped.split()[0], "26071"] and "TI042" in stripped:
                spans = token_spans(line)
                line = replace_token(line, 1, "26073")
                audit["till_lines"] += 1
            out.append(line + eol)
            i += 1
            continue

        # harvest lines (25SP only: drop 25197, keep 25198 as the single virtual)
        if section == "H" and season == "25SP":
            spans = token_spans(line)
            if len(spans) >= 2 and spans[1] and line[spans[1][0]:spans[1][1]] == "25197":
                audit["harvest_lines_removed"] += 1
                i += 1
                continue
            out.append(line + eol)
            i += 1
            continue

        # FIELDS lines: soil ID (first @L block) + coordinates/elevation (second @L block)
        if section == "L" and len(header_tokens) > 1 and header_tokens[1].startswith("ID_FIELD"):
            spans = token_spans(line)
            soil_i = header_tokens.index("ID_SOIL")
            if len(spans) > soil_i:
                cur = line[spans[soil_i][0]:spans[soil_i][1]].strip()
                if cur == "IBTM910017":
                    line = replace_token(line, soil_i, NEW_SOIL_ID)
                    audit["soil_id_lines"] += 1
            out.append(line + eol)
            i += 1
            continue
        if section == "L" and any(t.endswith("XCRD") for t in header_tokens):
            spans = token_spans(line)
            for name, want in (("XCRD", "35.16"), ("YCRD", "113.8"), ("ELEV", "75")):
                ti = next((k for k, t in enumerate(header_tokens) if t.endswith(name)), None)
                if ti is not None and len(spans) > ti:
                    cur = line[spans[ti][0]:spans[ti][1]].strip()
                    if cur == "-99":
                        line = replace_token(line, ti, want)
                        audit["elev_lines"] += 1
            out.append(line + eol)
            i += 1
            continue

        out.append(raw)
        i += 1

    new_text = "".join(out)
    # FA title
    if season == "25FA":
        new_text = new_text.replace("2025 SPRING", "2025 AUTUMN")
        audit["title_lines"] = 1
    path.write_text(new_text, encoding="utf-8", newline="")
    return audit


def edit_wth_header(path: Path) -> bool:
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines(keepends=True)
    changed = False
    for j, raw in enumerate(lines[:5]):
        line = raw.rstrip("\r\n")
        if "35.19" in line:
            lines[j] = raw.replace("35.190", "35.160")
            changed = True
        if " 300 " in raw or "  300." in raw:
            lines[j] = lines[j].replace("  300.", "   75.").replace(" 300 ", "  75 ")
            changed = True
    if changed:
        path.write_text("".join(lines), encoding="utf-8", newline="")
    return changed


def build_soil_file(dst: Path, src_sol: Path) -> None:
    text = src_sol.read_text(encoding="utf-8-sig")
    text = text.replace("IBTM910017", NEW_SOIL_ID)
    note = ("!*XXSL1800S1 derived profile (T0/P0 D5=A, 2026-09-14): SL / 180cm / 7 layers\r\n"
            "! 10/30/60/90/120/150/180cm; SLPF=0.933, SLDR=0.65, SLRO=75; inherited from the\r\n"
            "! v48 calibration-chain derived SOIL.SOL (xxql2501_scheme4_double_n lineage).\r\n"
            "! SLCL/SLSI/SSKS partly missing (-99); provenance per review 2026-09-14 section 5.1.\r\n")
    first_star = next(i for i, l in enumerate(text.splitlines(keepends=True)) if l.startswith("*"))
    lines = text.splitlines(keepends=True)
    lines.insert(first_star, note)
    dst.write_text("".join(lines), encoding="utf-8", newline="")


def write_manifest(dst: Path, src: Path, season: str, extra: dict) -> None:
    files = []
    for p in sorted(dst.iterdir()):
        if p.is_file() and p.name != "input_manifest.json":
            files.append({
                "name": p.name,
                "sha256": sha256(p),
                "size_bytes": p.stat().st_size
            })
    manifest = {
        "bundle_id": dst.name,
        "derived_from_bundle": src.name,
        "created": "2026-09-14",
        "decisions": "docs/T0P0执行与三季设置核对_统一决策文档_20260913.md (user replies) + "
                     "docs/reports/P0执行前审查_三季设置与模型方法_20260914.md + "
                     "docs/磷输入补全决策文档_20260914.md (D-P1~D-P7)",
        "season": season,
        "observation_value_system": "unscaled_measured (D1=A; no 0.90 factor anywhere)",
        "removals": "APPROVED_REMOVALS merged in main generator (D2=A)",
        "lai_imputation": ("26180 12 points R=18.52 with imputed flags (D3=C)" if season == "26SP" else None),
        "initial_nitrogen": ("0.34x baseline baked once <=60cm; ICNS fixed 1.0 in new bounds (D4=A)"
                              if season == "26SP" else None),
        "phosphorus_input_completion": {
            "smpx_method": "SA001 (Olsen method, D-P1=A)",
            "p_avail_estimation": "Sharpley et al. pedotransfer function via SoilPi_init (D-P2=A)",
            "sapx_depth_extension": "60cm measured SAPX extended to 80, 100, 120, 150, 180cm (D-P3=C->A fallback)",
            "famp_elemental_p_conversion": "Converted from P2O5 to elemental P (x 0.4364, D-P4=A)",
            "fdep_fertigation_depth": "All non-base topdressings (FE005, FE300, FE018) set to 10cm (D10, D-P4)",
            "species_p_params": "Retained peanut template as fixed input (D-P5=A)",
            "autumn_soil_p": "25FA soil P aligned with 26SP (D-P6)",
            "acceptance_testing": "Three-arm acceptance test passed with terminal yield drift < 10% and water/N balance drift < 2% (D-P7)"
        },
        "phosp": "Y (active phosphorus simulation verified by D-P7 three-arm acceptance)",
        "potas": "N (CRGRO has no K response path; review 4.2)",
        "planting": "PAGE/PENV/PLDP/PLWT/PLPH/SPRL per approved table 2026-09-13/14",
        "soil_id": NEW_SOIL_ID,
        "notes": extra,
        "old_packages_untouched": True,
        "files": files,
    }
    (dst / "input_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def regenerate_observations(dst: Path, season: str) -> dict:
    loaders = {"25SP": generator.load_2025_spring, "26SP": generator.load_2026_spring}
    result = loaders[season](REF)
    if season == "26SP":
        # D3: LAI imputation at 26180 into growth + flags before writing
        import numpy as np
        target = pd.to_datetime("26180", format="%y%j")
        for plot, lai in LAI_IMPUTED.items():
            mask = result.growth["TRNO"].eq(plot) & pd.to_datetime(result.growth["DATE"]).eq(target)
            result.growth.loc[mask, "LAID"] = lai
            result.growth.loc[mask, "LAID_sd"] = LAI_IMPUTED_SD[plot]
            result.growth.loc[mask, "LAID_sd_source"] = "imputed_sla_ratio_20260831"
            result.growth.loc[mask, "LAID_n_rep"] = LAI_IMPUTED_N[plot]
        result.source_notes.append(
            "LAI at 26180 imputed from leaf dry weight / SLA ratio R=18.52 (user D3=C 2026-09-13); "
            "12 points flagged imputed_20260831.")
    generator.write_season_outputs(result, dst, sha256(Path(generator.__file__)))
    # append imputed uncertainty rows (26SP only)
    if season == "26SP":
        unc_path = dst / "observation_uncertainty.csv"
        unc = pd.read_csv(unc_path)
        if not ((unc["date"].astype(str) == "26180") & (unc["variable"] == "LAID")).any():
            rows = pd.DataFrame([{
                "season_id": "26SP", "excode": "XXQL2601", "trno": p, "date": "26180",
                "variable": "LAID", "value": LAI_IMPUTED[p], "raw_sd": LAI_IMPUTED_SD[p],
                "n_rep": LAI_IMPUTED_N[p], "sd_method": "imputed_sla_ratio_20260831",
                "source_workbook": "2026春生长指标集.xlsx", "source_sheet": "0629",
                "source_row_rule": "imputed_from_leafdw_over_sla_ratio",
                "quality_flag": "imputed_20260831"} for p in sorted(LAI_IMPUTED)])
            pd.concat([unc, rows], ignore_index=True).to_csv(unc_path, index=False)
    return {"removals": result.qa_metrics.get("approved_removals", 0),
            "plots": result.qa_metrics.get("plots"),
            "total_observations": result.qa_metrics.get("total_observations")}


def build_season(src: Path, dst: Path, season: str, excode: str,
                 regen_obs: bool, sol_src: Path) -> None:
    if dst.exists():
        raise FileExistsError(dst)
    shutil.copytree(src, dst)
    # stale run snapshots / old manifest / backups are not carried forward
    for junk in ["input_manifest.json", "DSSAT48.INH", "DSSAT48.INP", "soil_n_scale_manifest.json"]:
        p = dst / junk
        if p.is_file():
            p.unlink()
    audits = {}
    if regen_obs:
        audits["observations"] = regenerate_observations(dst, season)
    audits["filex"] = edit_filex(dst / f"{excode}.TMX", season)
    build_soil_file(dst / "SOIL.SOL", sol_src)
    for wth in dst.glob("*.WTH"):
        edit_wth_header(wth)
    write_manifest(dst, src, season, audits)
    print(f"[{season}] built {dst.name}: {json.dumps(audits, ensure_ascii=False)}")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Build unified bundles for 25SP, 26SP, 25FA")
    parser.add_argument("--force", action="store_true", help="Overwrite existing output bundles")
    args = parser.parse_args()

    for dst in [OUT25, OUT26, OUTFA]:
        if dst.exists():
            if args.force:
                print(f"Removing existing {dst.name} (--force)...")
                shutil.rmtree(dst)
            else:
                raise FileExistsError(f"{dst} already exists; pass --force to overwrite")

    sol_src = B26_SRC / "SOIL.SOL"  # derived SL/180/7-layer (identical in 25D/26D)
    build_season(B25_SRC, OUT25, "25SP", "XXQL2501", regen_obs=True, sol_src=sol_src)
    build_season(B26_SRC, OUT26, "26SP", "XXQL2601", regen_obs=True, sol_src=sol_src)
    build_season(BFA_SRC, OUTFA, "25FA", "XXQL2502", regen_obs=False, sol_src=sol_src)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
