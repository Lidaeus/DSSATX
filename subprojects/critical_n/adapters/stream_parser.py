"""Fast fixed-column stream parser for DSSAT output files.

Reads PlantGro.OUT, PlantN.OUT, and FreshWt.OUT in pure Python line-by-line
streaming mode (< 10 ms execution target), preventing Pandas Cartesian product
overhead and memory allocations in hot inner loops.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union


@dataclass(frozen=True)
class PlantGroRecord:
    year: int
    doy: int
    das: int
    cwad: float
    gwad: float = 0.0
    laid: float = 0.0


@dataclass(frozen=True)
class PlantNRecord:
    year: int
    doy: int
    das: int
    cnad: float
    gnad: float = 0.0
    vnad: float = 0.0


@dataclass(frozen=True)
class FreshWtRecord:
    year: int
    doy: int
    das: int
    chpdt: float  # Cumulative harvested pod dry weight (kg/ha)
    chfpw: float = 0.0  # Cumulative fresh fruit weight (kg/ha)
    hpodw: float = 0.0  # Daily harvested pod weight (kg/ha)


@dataclass(frozen=True)
class DailyMergedRecord:
    run_id: int
    treatment_id: int
    year: int
    doy: int
    das: int
    cwad: float
    cnad: float
    chpdt: float = 0.0
    hpodw: float = 0.0
    has_fresh_wt: bool = False


def parse_plant_gro_stream(file_path: Union[str, Path]) -> dict[int, dict[int, PlantGroRecord]]:
    """Parse PlantGro.OUT into {run_id: {das: PlantGroRecord}}.

    Zero-pandas pure streaming parser. Multi-run block isolated.
    """
    path = Path(file_path)
    if not path.is_file():
        return {}

    gro_data: dict[int, dict[int, PlantGroRecord]] = {}
    current_run: Optional[int] = None
    idx_year = idx_doy = idx_das = idx_cwad = idx_gwad = idx_laid = None

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("*RUN"):
                parts = stripped.split()
                run_token = parts[1].rstrip(":") if len(parts) > 1 else "1"
                current_run = int(run_token) if run_token.isdigit() else 1
                gro_data[current_run] = {}
                idx_year = idx_doy = idx_das = idx_cwad = idx_gwad = idx_laid = None
                continue

            if current_run is None:
                continue

            if stripped.startswith("@YEAR"):
                parts = line.split()
                idx_year = parts.index("YEAR") if "YEAR" in parts else 0
                idx_doy = parts.index("DOY") if "DOY" in parts else 1
                idx_das = parts.index("DAS") if "DAS" in parts else None
                idx_cwad = parts.index("CWAD") if "CWAD" in parts else None
                idx_gwad = parts.index("GWAD") if "GWAD" in parts else None
                idx_laid = parts.index("LAID") if "LAID" in parts else None
                continue

            if idx_cwad is None or idx_das is None or line.startswith("*") or line.startswith("!"):
                continue

            parts = line.split()
            max_idx = max(idx_das, idx_cwad, idx_year or 0, idx_doy or 1)
            if len(parts) > max_idx:
                try:
                    das = int(float(parts[idx_das]))
                    cwad = float(parts[idx_cwad])
                    year = int(parts[idx_year]) if idx_year is not None else 0
                    doy = int(parts[idx_doy]) if idx_doy is not None else 0
                    gwad = float(parts[idx_gwad]) if (idx_gwad is not None and len(parts) > idx_gwad) else 0.0
                    laid = float(parts[idx_laid]) if (idx_laid is not None and len(parts) > idx_laid) else 0.0
                    gro_data[current_run][das] = PlantGroRecord(
                        year=year, doy=doy, das=das, cwad=cwad, gwad=gwad, laid=laid
                    )
                except (ValueError, IndexError):
                    pass

    return gro_data


def parse_plant_n_stream(file_path: Union[str, Path]) -> dict[int, dict[int, PlantNRecord]]:
    """Parse PlantN.OUT into {run_id: {das: PlantNRecord}}.

    Zero-pandas pure streaming parser. Multi-run block isolated.
    """
    path = Path(file_path)
    if not path.is_file():
        return {}

    n_data: dict[int, dict[int, PlantNRecord]] = {}
    current_run: Optional[int] = None
    idx_year = idx_doy = idx_das = idx_cnad = idx_gnad = idx_vnad = None

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("*RUN"):
                parts = stripped.split()
                run_token = parts[1].rstrip(":") if len(parts) > 1 else "1"
                current_run = int(run_token) if run_token.isdigit() else 1
                n_data[current_run] = {}
                idx_year = idx_doy = idx_das = idx_cnad = idx_gnad = idx_vnad = None
                continue

            if current_run is None:
                continue

            if stripped.startswith("@YEAR"):
                parts = line.split()
                idx_year = parts.index("YEAR") if "YEAR" in parts else 0
                idx_doy = parts.index("DOY") if "DOY" in parts else 1
                idx_das = parts.index("DAS") if "DAS" in parts else None
                idx_cnad = parts.index("CNAD") if "CNAD" in parts else None
                idx_gnad = parts.index("GNAD") if "GNAD" in parts else None
                idx_vnad = parts.index("VNAD") if "VNAD" in parts else None
                continue

            if idx_cnad is None or idx_das is None or line.startswith("*") or line.startswith("!"):
                continue

            parts = line.split()
            max_idx = max(idx_das, idx_cnad, idx_year or 0, idx_doy or 1)
            if len(parts) > max_idx:
                try:
                    das = int(float(parts[idx_das]))
                    cnad = float(parts[idx_cnad])
                    year = int(parts[idx_year]) if idx_year is not None else 0
                    doy = int(parts[idx_doy]) if idx_doy is not None else 0
                    gnad = float(parts[idx_gnad]) if (idx_gnad is not None and len(parts) > idx_gnad) else 0.0
                    vnad = float(parts[idx_vnad]) if (idx_vnad is not None and len(parts) > idx_vnad) else 0.0
                    n_data[current_run][das] = PlantNRecord(
                        year=year, doy=doy, das=das, cnad=cnad, gnad=gnad, vnad=vnad
                    )
                except (ValueError, IndexError):
                    pass

    return n_data


def parse_fresh_wt_stream(file_path: Union[str, Path]) -> dict[int, dict[int, FreshWtRecord]]:
    """Parse FreshWt.OUT into {run_id: {das: FreshWtRecord}}.

    Extracts direct cumulative harvested pod weight CHPDT and event HPODW.
    """
    path = Path(file_path)
    if not path.is_file():
        return {}

    fresh_data: dict[int, dict[int, FreshWtRecord]] = {}
    current_run: Optional[int] = None
    idx_year = idx_doy = idx_das = idx_chpdt = idx_chfpw = idx_hpodw = None

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("*RUN"):
                parts = stripped.split()
                run_token = parts[1].rstrip(":") if len(parts) > 1 else "1"
                current_run = int(run_token) if run_token.isdigit() else 1
                fresh_data[current_run] = {}
                idx_year = idx_doy = idx_das = idx_chpdt = idx_chfpw = idx_hpodw = None
                continue

            if current_run is None:
                continue

            if stripped.startswith("@YEAR"):
                parts = line.split()
                idx_year = parts.index("YEAR") if "YEAR" in parts else 0
                idx_doy = parts.index("DOY") if "DOY" in parts else 1
                idx_das = parts.index("DAS") if "DAS" in parts else None
                idx_chpdt = parts.index("CHPDT") if "CHPDT" in parts else None
                idx_chfpw = parts.index("CHFPW") if "CHFPW" in parts else None
                idx_hpodw = parts.index("HPODW") if "HPODW" in parts else None
                continue

            if idx_chpdt is None or idx_das is None or line.startswith("*") or line.startswith("!"):
                continue

            parts = line.split()
            max_idx = max(idx_das, idx_chpdt, idx_year or 0, idx_doy or 1)
            if len(parts) > max_idx:
                try:
                    das = int(float(parts[idx_das]))
                    chpdt = float(parts[idx_chpdt])
                    year = int(parts[idx_year]) if idx_year is not None else 0
                    doy = int(parts[idx_doy]) if idx_doy is not None else 0
                    chfpw = float(parts[idx_chfpw]) if (idx_chfpw is not None and len(parts) > idx_chfpw) else 0.0
                    hpodw = float(parts[idx_hpodw]) if (idx_hpodw is not None and len(parts) > idx_hpodw) else 0.0
                    fresh_data[current_run][das] = FreshWtRecord(
                        year=year, doy=doy, das=das, chpdt=chpdt, chfpw=chfpw, hpodw=hpodw
                    )
                except (ValueError, IndexError):
                    pass

    return fresh_data


def parse_treatment_ids_from_plantgro(file_path: Union[str, Path]) -> dict[int, int]:
    """Parse {run_id: treatment_id} mapping from TREATMENT lines in PlantGro.OUT."""
    path = Path(file_path)
    if not path.is_file():
        return {}

    run_trt_map: dict[int, int] = {}
    current_run = 1

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("*RUN"):
                parts = stripped.split()
                run_token = parts[1].rstrip(":") if len(parts) > 1 else "1"
                if run_token.isdigit():
                    current_run = int(run_token)
                continue
            if stripped.startswith("TREATMENT"):
                # e.g.: TREATMENT  2   : ... or TREATMENT 2: ...
                parts = stripped.split()
                if len(parts) >= 2:
                    trt_token = parts[1].rstrip(":")
                    if trt_token.isdigit():
                        run_trt_map[current_run] = int(trt_token)

    return run_trt_map


def load_merged_nitrogen_series(
    run_dir: Union[str, Path],
) -> dict[int, list[DailyMergedRecord]]:
    """Parse and merge PlantGro, PlantN, and FreshWt into structured records per run.

    Returns {run_id: [DailyMergedRecord, ...]} sorted by DAS.
    """
    dir_path = Path(run_dir)
    gro_file = dir_path / "PlantGro.OUT"
    n_file = dir_path / "PlantN.OUT"
    fresh_file = dir_path / "FreshWt.OUT"

    gro_data = parse_plant_gro_stream(gro_file)
    n_data = parse_plant_n_stream(n_file)
    fresh_data = parse_fresh_wt_stream(fresh_file) if fresh_file.is_file() else {}
    trt_map = parse_treatment_ids_from_plantgro(gro_file)

    all_runs = sorted(gro_data.keys())
    merged: dict[int, list[DailyMergedRecord]] = {}

    for run_id in all_runs:
        trt_id = trt_map.get(run_id, run_id)
        run_gro = gro_data[run_id]
        run_n = n_data.get(run_id, {})
        run_fresh = fresh_data.get(run_id, {})
        has_fresh_wt = bool(run_fresh)

        records: list[DailyMergedRecord] = []
        for das in sorted(run_gro.keys()):
            gro_rec = run_gro[das]
            n_rec = run_n.get(das)
            cnad = n_rec.cnad if n_rec else 0.0
            fresh_rec = run_fresh.get(das)
            chpdt = fresh_rec.chpdt if fresh_rec else 0.0
            hpodw = fresh_rec.hpodw if fresh_rec else 0.0

            records.append(
                DailyMergedRecord(
                    run_id=run_id,
                    treatment_id=trt_id,
                    year=gro_rec.year,
                    doy=gro_rec.doy,
                    das=das,
                    cwad=gro_rec.cwad,
                    cnad=cnad,
                    chpdt=chpdt,
                    hpodw=hpodw,
                    has_fresh_wt=has_fresh_wt,
                )
            )
        merged[run_id] = records

    return merged
