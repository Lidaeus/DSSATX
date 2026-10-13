"""Exporter for PestCNC.OUT with rigid fixed-column invariant.

Guarantees:
1. Exact fixed-width column layout:
   @RUN TRT YEAR  DOY  DAS    CWAD_T     N_ACT   NC_CRIT       NNI
2. Rigid line-count invariance:
   Pre-emergence / zero-biomass steps (W_eff < 0.05 t/ha or CWAD <= 0)
   are written with sentinel values (-99.000) instead of being dropped.
   This guarantees that PEST++ .ins instruction line pointers never lose alignment.
3. Multi-harvest continuity:
   Incorporates cumulative harvested fruit mass and N from FreshWt.OUT.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Union

import pandas as pd

from subprojects.critical_n.adapters.stream_parser import (
    DailyMergedRecord,
    load_merged_nitrogen_series,
)
from subprojects.critical_n.core.dilution_curve import (
    DEFAULT_CNC_A,
    DEFAULT_CNC_B,
    DEFAULT_CNC_W0,
    SENTINEL_VALUE,
)
from subprojects.critical_n.core.effective_biomass import (
    CumulativeStateTracker,
    MIN_CANOPY_BIOMASS_T_HA,
)

PEST_CNC_FILENAME: str = "PestCNC.OUT"
HEADER_TITLE: str = "*NITROGEN NUTRITION INDEX OBSERVATIONS\n"
HEADER_COLUMNS: str = "@RUN TRT YEAR  DOY  DAS    CWAD_T     N_ACT   NC_CRIT        NNI\n"


def format_pest_cnc_line(
    run_id: int,
    trt_id: int,
    year: int,
    doy: int,
    das: int,
    w_t: float,
    n_act: float,
    nc_crit: float,
    nni_val: float,
) -> str:
    """Format a single record line into exact fixed-width fields.

    Layout:
      run_id:  5 chars (1-5)
      trt_id:  4 chars (6-9)
      year:    5 chars (10-14)
      doy:     5 chars (15-19)
      das:     5 chars (20-24)
      w_t:    10 chars (25-34, 10.3f)
      n_act:  10 chars (35-44, 10.3f)
      nc_crit:10 chars (45-54, 10.3f)
      nni_val:10 chars (55-64, 10.3f)
    """
    import math

    safe_w = -99.0 if (math.isnan(w_t) or math.isinf(w_t)) else w_t
    safe_n = -99.0 if (math.isnan(n_act) or math.isinf(n_act)) else n_act
    safe_nc = -99.0 if (math.isnan(nc_crit) or math.isinf(nc_crit)) else nc_crit
    safe_nni = -99.0 if (math.isnan(nni_val) or math.isinf(nni_val)) else nni_val

    return (
        f"{run_id:5d}"
        f"{trt_id:4d}"
        f"{year:5d}"
        f"{doy:5d}"
        f"{das:5d}"
        f"{safe_w:10.3f}"
        f"{safe_n:10.3f}"
        f"{safe_nc:10.3f}"
        f"{safe_nni:10.3f}\n"
    )


def export_pest_cnc(
    run_dir: Union[str, Path],
    out_file: Optional[Union[str, Path]] = None,
    cnc_a: float = DEFAULT_CNC_A,
    cnc_b: float = DEFAULT_CNC_B,
    cnc_w0: float = DEFAULT_CNC_W0,
    default_fruit_n_pct: float = 1.78,
) -> Path:
    """Parse DSSAT outputs in `run_dir` and write `PestCNC.OUT`.

    Parameters
    ----------
    run_dir : Path or str
        Directory containing PlantGro.OUT, PlantN.OUT, and optionally FreshWt.OUT.
    out_file : Path or str, optional
        Target path for output file. Default is `run_dir / "PestCNC.OUT"`.
    cnc_a, cnc_b, cnc_w0 : float, optional
        Critical dilution curve parameters. Default to frozen values (4.85, 0.38, 1.00).
    default_fruit_n_pct : float, optional
        Fruit dry-basis N concentration percentage (%), default 1.78%.

    Returns
    -------
    Path
        Absolute path to the written PestCNC.OUT file.
    """
    dir_path = Path(run_dir)
    target_path = Path(out_file) if out_file else dir_path / PEST_CNC_FILENAME

    runs_data = load_merged_nitrogen_series(dir_path)
    if not runs_data:
        # Fallback empty rigid header with one sentinel row
        target_path.write_text(
            HEADER_TITLE
            + HEADER_COLUMNS
            + format_pest_cnc_line(1, 1, -99, -99, -99, -99.0, -99.0, -99.0, -99.0),
            encoding="utf-8",
        )
        return target_path

    lines: list[str] = [HEADER_TITLE, HEADER_COLUMNS]
    tracker = CumulativeStateTracker(
        cnc_a=cnc_a,
        cnc_b=cnc_b,
        cnc_w0=cnc_w0,
        default_fruit_n_pct=default_fruit_n_pct,
    )

    for run_id in sorted(runs_data.keys()):
        tracker.reset()
        records = runs_data[run_id]

        for rec in records:
            step_res = tracker.step(
                das=rec.das,
                cwad=rec.cwad,
                cnad=rec.cnad,
                direct_chpdt=rec.chpdt if rec.has_fresh_wt else None,
            )

            lines.append(
                format_pest_cnc_line(
                    run_id=rec.run_id,
                    trt_id=rec.treatment_id,
                    year=rec.year,
                    doy=rec.doy,
                    das=rec.das,
                    w_t=step_res.w_eff,
                    n_act=step_res.n_act_cum,
                    nc_crit=step_res.nc_crit,
                    nni_val=step_res.nni_val,
                )
            )

    target_path.write_text("".join(lines), encoding="utf-8")
    return target_path


def export_cnc_dataframe(
    run_dir: Union[str, Path],
    cnc_a: float = DEFAULT_CNC_A,
    cnc_b: float = DEFAULT_CNC_B,
    cnc_w0: float = DEFAULT_CNC_W0,
    default_fruit_n_pct: float = 1.78,
) -> pd.DataFrame:
    """Parse DSSAT outputs and return a tidy DataFrame of CNC trajectory states."""
    dir_path = Path(run_dir)
    runs_data = load_merged_nitrogen_series(dir_path)

    rows = []
    tracker = CumulativeStateTracker(
        cnc_a=cnc_a,
        cnc_b=cnc_b,
        cnc_w0=cnc_w0,
        default_fruit_n_pct=default_fruit_n_pct,
    )

    for run_id in sorted(runs_data.keys()):
        tracker.reset()
        for rec in runs_data[run_id]:
            step_res = tracker.step(
                das=rec.das,
                cwad=rec.cwad,
                cnad=rec.cnad,
                direct_chpdt=rec.chpdt if rec.has_fresh_wt else None,
            )
            rows.append(
                {
                    "run_id": rec.run_id,
                    "treatment_id": rec.treatment_id,
                    "year": rec.year,
                    "doy": rec.doy,
                    "das": rec.das,
                    "cwad": rec.cwad,
                    "cnad": rec.cnad,
                    "cum_harvest_dm": step_res.cum_harvest_dm,
                    "cum_harvest_n": step_res.cum_harvest_n,
                    "w_standing": step_res.w_standing,
                    "w_eff": step_res.w_eff,
                    "n_act_standing": step_res.n_act_standing,
                    "n_act_cum": step_res.n_act_cum,
                    "nc_crit": step_res.nc_crit,
                    "nni": step_res.nni_val,
                    "is_valid": step_res.is_valid,
                }
            )

    return pd.DataFrame(rows)
