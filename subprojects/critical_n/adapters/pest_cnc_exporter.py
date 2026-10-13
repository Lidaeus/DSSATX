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
from collections.abc import Mapping
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
    DEFAULT_CNC_NC_INF,
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
HEADER_COLUMNS_WITH_RTOL: str = "@RUN TRT YEAR  DOY  DAS    CWAD_T     N_ACT   NC_CRIT        NNI     R_TOL\n"


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
    r_tol: Optional[float] = None,
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
      r_tol:  10 chars (65-74, 10.3f, optional)
    """
    import math

    safe_w = -99.0 if (math.isnan(w_t) or math.isinf(w_t)) else w_t
    safe_n = -99.0 if (math.isnan(n_act) or math.isinf(n_act)) else n_act
    safe_nc = -99.0 if (math.isnan(nc_crit) or math.isinf(nc_crit)) else nc_crit
    safe_nni = -99.0 if (math.isnan(nni_val) or math.isinf(nni_val)) else nni_val

    base_str = (
        f"{run_id:5d}"
        f"{trt_id:4d}"
        f"{year:5d}"
        f"{doy:5d}"
        f"{das:5d}"
        f"{safe_w:10.3f}"
        f"{safe_n:10.3f}"
        f"{safe_nc:10.3f}"
        f"{safe_nni:10.3f}"
    )
    if r_tol is not None:
        safe_rtol = -99.0 if (math.isnan(r_tol) or math.isinf(r_tol)) else r_tol
        return f"{base_str}{safe_rtol:10.3f}\n"
    return f"{base_str}\n"


def export_pest_cnc(
    run_dir: Union[str, Path],
    out_file: Optional[Union[str, Path]] = None,
    cnc_a: float = DEFAULT_CNC_A,
    cnc_b: float = DEFAULT_CNC_B,
    cnc_w0: float = DEFAULT_CNC_W0,
    cnc_nc_inf: float = DEFAULT_CNC_NC_INF,
    default_fruit_n_pct: float = 1.78,
    include_r_tol: bool = False,
    treatment_n_levels: Optional[Union[Mapping[int, str], str, Path, pd.DataFrame]] = None,
    strict_treatment_mapping: bool = False,
) -> Path:
    """Parse DSSAT outputs in `run_dir` and write `PestCNC.OUT`.

    Parameters
    ----------
    run_dir : Path or str
        Directory containing PlantGro.OUT, PlantN.OUT, and optionally FreshWt.OUT.
    out_file : Path or str, optional
        Target path for output file. Default is `run_dir / "PestCNC.OUT"`.
    cnc_a, cnc_b, cnc_w0, cnc_nc_inf : float, optional
        Critical dilution curve parameters. Default to frozen values (4.85, 0.38, 1.00, 1.70).
    default_fruit_n_pct : float, optional
        Fruit dry-basis N concentration percentage (%), default 1.78%.
    include_r_tol : bool, optional
        If True, appends column R_TOL using physiological tolerance intervals.
    treatment_n_levels : Mapping, DataFrame, Path, or str, optional
        Mapping of treatment_id -> nitrogen level ('N0', 'N1', 'N2', 'N3').
        Auto-discovered from treatment_metadata.csv if None.
    strict_treatment_mapping : bool, optional
        If True, raises ValueError if a treatment has no N level mapping when include_r_tol is True.

    Returns
    -------
    Path
        Absolute path to the written PestCNC.OUT file.
    """
    from subprojects.critical_n.core.objective_penalty import (
        PHYSIOLOGICAL_NNI_INTERVALS,
        relaxed_pseudo_huber_residual,
    )

    dir_path = Path(run_dir)
    target_path = Path(out_file) if out_file else dir_path / PEST_CNC_FILENAME

    runs_data = load_merged_nitrogen_series(dir_path)
    header_col = HEADER_COLUMNS_WITH_RTOL if include_r_tol else HEADER_COLUMNS

    if not runs_data:
        # Fallback empty rigid header with one sentinel row
        sentinel_r_tol = -99.0 if include_r_tol else None
        target_path.write_text(
            HEADER_TITLE
            + header_col
            + format_pest_cnc_line(1, 1, -99, -99, -99, -99.0, -99.0, -99.0, -99.0, r_tol=sentinel_r_tol),
            encoding="utf-8",
        )
        return target_path

    lines: list[str] = [HEADER_TITLE, header_col]
    tracker = CumulativeStateTracker(
        cnc_a=cnc_a,
        cnc_b=cnc_b,
        cnc_w0=cnc_w0,
        cnc_nc_inf=cnc_nc_inf,
        default_fruit_n_pct=default_fruit_n_pct,
    )

    if include_r_tol:
        if treatment_n_levels is None or not isinstance(treatment_n_levels, Mapping):
            from subprojects.critical_n.calibration.cnc_builder import resolve_treatment_n_levels
            n_map = resolve_treatment_n_levels(dir_path, treatment_n_levels)
        else:
            n_map = {int(k): str(v) for k, v in treatment_n_levels.items()}
    else:
        n_map = {}

    for run_id in sorted(runs_data.keys()):
        tracker.reset()
        records = runs_data[run_id]

        for rec in records:
            step_res = tracker.step(
                das=rec.das,
                cwad=rec.cwad,
                cnad=rec.cnad,
                direct_chpdt=rec.chpdt if rec.has_fresh_wt else None,
                direct_chpdtn=rec.chpdtn if (rec.has_fresh_wt and rec.has_chpdtn) else None,
            )

            r_tol_val: Optional[float] = None
            if include_r_tol:
                if step_res.is_valid and step_res.nni_val >= 0.0:
                    if rec.treatment_id not in n_map:
                        if strict_treatment_mapping:
                            raise ValueError(
                                f"Treatment {rec.treatment_id} has no nitrogen level mapping in {n_map}. "
                                f"Silent fallback to 'N2' is prohibited by R0 protocol."
                            )
                        n_level = "N2"
                    else:
                        n_level = n_map[rec.treatment_id]
                    lo, hi = PHYSIOLOGICAL_NNI_INTERVALS.get(n_level, (0.85, 1.15))
                    r_tol_val = relaxed_pseudo_huber_residual(step_res.nni_val, lo, hi)
                else:
                    r_tol_val = -99.0

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
                    r_tol=r_tol_val,
                )
            )

    target_path.write_text("".join(lines), encoding="utf-8")
    return target_path


def export_cnc_dataframe(
    run_dir: Union[str, Path],
    cnc_a: float = DEFAULT_CNC_A,
    cnc_b: float = DEFAULT_CNC_B,
    cnc_w0: float = DEFAULT_CNC_W0,
    cnc_nc_inf: float = DEFAULT_CNC_NC_INF,
    default_fruit_n_pct: float = 1.78,
    treatment_n_levels: Optional[Union[Mapping[int, str], str, Path, pd.DataFrame]] = None,
) -> pd.DataFrame:
    """Parse DSSAT outputs and return a tidy DataFrame of CNC trajectory states."""
    from subprojects.critical_n.core.objective_penalty import (
        PHYSIOLOGICAL_NNI_INTERVALS,
        relaxed_pseudo_huber_residual,
    )

    dir_path = Path(run_dir)
    runs_data = load_merged_nitrogen_series(dir_path)

    if treatment_n_levels is None or not isinstance(treatment_n_levels, Mapping):
        from subprojects.critical_n.calibration.cnc_builder import resolve_treatment_n_levels
        n_map = resolve_treatment_n_levels(dir_path, treatment_n_levels)
    else:
        n_map = {int(k): str(v) for k, v in treatment_n_levels.items()}

    rows = []
    tracker = CumulativeStateTracker(
        cnc_a=cnc_a,
        cnc_b=cnc_b,
        cnc_w0=cnc_w0,
        cnc_nc_inf=cnc_nc_inf,
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
                direct_chpdtn=rec.chpdtn if (rec.has_fresh_wt and rec.has_chpdtn) else None,
            )

            r_tol_val: float = -99.0
            if step_res.is_valid and step_res.nni_val >= 0.0:
                n_level = n_map.get(rec.treatment_id, "N2")
                lo, hi = PHYSIOLOGICAL_NNI_INTERVALS.get(n_level, (0.85, 1.15))
                r_tol_val = relaxed_pseudo_huber_residual(step_res.nni_val, lo, hi)

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
                    "chpdtn": step_res.chpdtn,
                    "has_chpdtn": rec.has_chpdtn,
                    "w_standing": step_res.w_standing,
                    "w_eff": step_res.w_eff,
                    "n_act_standing": step_res.n_act_standing,
                    "n_act_cum": step_res.n_act_cum,
                    "nc_crit": step_res.nc_crit,
                    "nni": step_res.nni_val,
                    "r_tol": r_tol_val,
                    "is_valid": step_res.is_valid,
                }
            )

    return pd.DataFrame(rows)
