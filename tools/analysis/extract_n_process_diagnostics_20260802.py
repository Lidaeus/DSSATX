#!/usr/bin/env python3
"""Extract available CROPGRO plant-N/stress diagnostics from the G115 trial.

The native CROPGRO PlantN.OUT/PlantGro.OUT files do not expose every internal
state requested by the nitrogen-chain audit.  This script exports all
available fields and records unavailable states explicitly instead of
silently treating a proxy as the exact variable.
"""
from __future__ import annotations

import re
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "workspace/diagnostics/n_min_tissue_response_20260802"
OUT = RUN / "process_diagnostics"
CASES = ["G100", "G115", "G120", "G130", "G140", "G115_leaf", "G115_stem", "G115_root"]

MAP = {
    "25SP": {2: ("W3", "N3"), 3: ("W3", "N2"), 4: ("W3", "N1"), 5: ("W3", "N0"),
             10: ("W1", "N3"), 11: ("W1", "N2"), 12: ("W1", "N1"), 13: ("W1", "N0")},
    "26SP": {1: ("W3", "N3"), 4: ("W3", "N2"), 7: ("W3", "N1"), 9: ("W3", "N0"),
             3: ("W1", "N3"), 6: ("W1", "N2"), 10: ("W1", "N1"), 12: ("W1", "N0")},
}


def parse_sections(path: Path) -> dict[int, pd.DataFrame]:
    sections: dict[int, pd.DataFrame] = {}
    run = None
    header = None
    rows = []
    def flush():
        nonlocal rows, header
        if run is not None and header and rows:
            sections[run] = pd.DataFrame(rows, columns=header)
        rows, header = [], None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = raw.strip()
        m = re.match(r"\*RUN\s+(\d+)", s, re.I)
        if m:
            flush(); run = int(m.group(1)); continue
        if s.startswith("@"):
            if s.upper().startswith("@YEAR"):
                header = s.split()
            continue
        if not header or run is None or not s or s.startswith("*") or s.startswith("!"):
            continue
        parts = s.split()
        if len(parts) < len(header):
            continue
        try:
            [float(x) for x in parts[:len(header)]]
        except ValueError:
            continue
        rows.append(parts[:len(header)])
    flush()
    for k, df in sections.items():
        for c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return sections


def parse_case(case: str) -> pd.DataFrame:
    rows = []
    for season in ("25SP", "26SP"):
        sdir = RUN / case / "_seasons" / season
        mapping = pd.read_csv(RUN / case / f"{case}_run_mapping.csv")
        mapping = mapping[mapping.season_id.eq(season)]
        pn = parse_sections(sdir / "PlantN.OUT")
        pg = parse_sections(sdir / "PlantGro.OUT")
        sn = parse_sections(sdir / "SoilNi.OUT")
        chpdt = pd.read_csv(RUN / "chpdt_by_treatment.csv")
        for r in mapping.itertuples(index=False):
            w, n = MAP[season][int(r.treatment)]
            pnd = pn.get(int(r.local_run), pd.DataFrame())
            pgd = pg.get(int(r.local_run), pd.DataFrame())
            if pnd.empty or pgd.empty:
                continue
            pnd = pnd.sort_values("DAP")
            pgd = pgd.sort_values("DAP")
            snd = sn.get(int(r.local_run), pd.DataFrame()).sort_values("DAS")
            lastn, lastg = pnd.iloc[-1], pgd.iloc[-1]
            nup = pd.to_numeric(pnd.get("NUPC"), errors="coerce").dropna()
            d_nup = nup.diff().dropna()
            nstd = pd.to_numeric(pgd.get("NSTD"), errors="coerce").dropna()
            mineral_cols = [c for c in snd.columns if re.fullmatch(r"NT\d+D?", str(c))]
            mineral_sum = float(pd.to_numeric(snd.iloc[-1][mineral_cols], errors="coerce").sum()) if mineral_cols else float("nan")
            yield_row = chpdt[(chpdt.case == case) & (chpdt.season == season) & (chpdt.treatment == int(r.treatment))]
            chpdt_terminal = float(yield_row.iloc[0]["CHPDT"]) if not yield_row.empty else float("nan")
            row = {
                "case": case, "season": season, "water": w, "nitrogen": n,
                "treatment": int(r.treatment), "local_run": int(r.local_run),
                "DAP_terminal": float(lastn.get("DAP", float("nan"))),
                "NUPC_terminal_g_per_plant": float(lastn.get("NUPC", float("nan"))),
                "daily_NUPC_increment_mean_g_per_plant": float(d_nup.mean()) if len(d_nup) else float("nan"),
                "CNAD_terminal_kgN_ha": float(lastn.get("CNAD", float("nan"))),
                "VNAD_terminal_kgN_ha": float(lastn.get("VNAD", float("nan"))),
                "LNAD_terminal_kgN_ha": float(lastn.get("LNAD", float("nan"))),
                "SNAD_terminal_kgN_ha": float(lastn.get("SNAD", float("nan"))),
                "leaf_N_pct_terminal": float(lastn.get("LN%D", float("nan"))),
                "stem_N_pct_terminal": float(lastn.get("SN%D", float("nan"))),
                "NSTD_mean_stress_proxy": float(nstd.mean()) if len(nstd) else float("nan"),
                "NSTRES_proxy_mean_1_minus_NSTD": float(1.0 - nstd.mean()) if len(nstd) else float("nan"),
                "soil_inorganic_N_terminal_sum_ppm": mineral_sum,
                "LAID_terminal": float(lastg.get("LAID", float("nan"))),
                "LWAD_terminal": float(lastg.get("LWAD", float("nan"))),
                "SWAD_terminal": float(lastg.get("SWAD", float("nan"))),
                "fruit_weight_proxy_PWAD": float(lastg.get("PWAD", float("nan"))),
                "harvest_index_proxy_HIAD": float(lastg.get("HIAD", float("nan"))),
                "pod_harvest_index_proxy_HIPD": float(lastg.get("HIPD", float("nan"))),
                "CHPDT_terminal_kg_ha": chpdt_terminal,
            }
            row["fruit_to_veg_mass_proxy"] = chpdt_terminal / max(row["LWAD_terminal"] + row["SWAD_terminal"], 1e-9)
            rows.append(row)
    return pd.DataFrame(rows)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    frames = [parse_case(c) for c in CASES]
    detail = pd.concat(frames, ignore_index=True)
    detail.to_csv(OUT / "plant_n_process_by_treatment.csv", index=False)
    summary = detail.groupby(["case", "season", "water", "nitrogen"], as_index=False).mean(numeric_only=True)
    summary.to_csv(OUT / "plant_n_process_summary.csv", index=False)
    availability = pd.DataFrame([
        ("TRNU", "unavailable", "not written by CROPGRO PlantN.OUT/PlantGro.OUT"),
        ("NDMNEW", "unavailable", "internal daily N demand is not written"),
        ("SUPPN/NDMNEW", "unavailable", "requires TRNU+NMINEA and NDMNEW"),
        ("NSTRES", "proxy", "PlantGro NSTD is mean(1-NSTRES) over output interval; NSTRES_proxy=1-NSTD"),
        ("leaf_N", "available", "PlantN LN%D"),
        ("fruit_allocation", "proxy", "PlantGro PWAD/HIAD/HIPD; exact carbon allocation state unavailable"),
        ("N uptake", "available", "PlantN NUPC cumulative uptake; daily delta is an actual-uptake proxy, not TRNU"),
    ], columns=["requested_variable", "status", "definition"])
    availability.to_csv(OUT / "variable_availability_audit.csv", index=False)
    (OUT / "README.md").write_text(
        "# G115 氮过程诊断\n\n"
        "PlantN.OUT and PlantGro.OUT were retained with `--keep-nitrogen-outputs`. "
        "TRNU, NDMNEW and SUPPN/NDMNEW are internal CROPGRO states and are not present in native output; they are recorded as unavailable rather than inferred. "
        "NUPC, organ N amounts/concentrations, NSTD stress proxy, LAI/organ mass and harvest-index proxies are exported.\n",
        encoding="utf-8",
    )
    print(summary.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
