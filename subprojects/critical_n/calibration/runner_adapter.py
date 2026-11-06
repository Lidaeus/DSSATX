"""DSSAT execution post-processing adapter for CNC (Scheme A).

Provides drop-in, zero-disruption post-processing hooks to generate PestCNC.OUT
after DSSAT completes execution, without modifying core src/dssat/run_dssat.py.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable, Optional, Union

from subprojects.critical_n.adapters.pest_cnc_exporter import (
    PEST_CNC_FILENAME,
    export_pest_cnc,
)
from subprojects.critical_n.core.dilution_curve import (
    DEFAULT_CNC_A,
    DEFAULT_CNC_B,
    DEFAULT_CNC_NC_INF,
    DEFAULT_CNC_W0,
)

logger = logging.getLogger(__name__)


def post_process_dssat_cnc(
    run_dir: Union[str, Path],
    cnc_a: float = DEFAULT_CNC_A,
    cnc_b: float = DEFAULT_CNC_B,
    cnc_w0: float = DEFAULT_CNC_W0,
    cnc_nc_inf: float = DEFAULT_CNC_NC_INF,
    default_fruit_n_pct: float = 1.78,
    include_r_tol: bool = False,
    treatment_n_levels: Optional[Any] = None,
    raise_on_error: bool = False,
) -> Optional[Path]:
    """Execute post-processing on DSSAT outputs to generate PestCNC.OUT.

    Parameters
    ----------
    run_dir : Path or str
        DSSAT execution directory.
    cnc_a, cnc_b, cnc_w0, cnc_nc_inf : float, optional
        Critical nitrogen dilution parameters (default frozen invariants).
    default_fruit_n_pct : float, optional
        Default fruit dry basis N percentage (1.78%).
    include_r_tol : bool, optional
        If True, includes R_TOL relaxed Pseudo-Huber residual column.
    treatment_n_levels : optional
        Treatment -> nitrogen level mapping.
    raise_on_error : bool, optional
        If True, re-raises any exception encountered during post-processing.
        Default False (logs warning, does not crash execution).

    Returns
    -------
    Optional[Path]
        Path to PestCNC.OUT if successfully generated, else None.
    """
    path = Path(run_dir)
    gro_file = path / "PlantGro.OUT"
    n_file = path / "PlantN.OUT"

    if not (gro_file.is_file() and n_file.is_file()):
        logger.debug(f"PlantGro.OUT or PlantN.OUT not found in {run_dir}, skipping CNC export.")
        return None

    try:
        out_path = export_pest_cnc(
            run_dir=path,
            cnc_a=cnc_a,
            cnc_b=cnc_b,
            cnc_w0=cnc_w0,
            cnc_nc_inf=cnc_nc_inf,
            default_fruit_n_pct=default_fruit_n_pct,
            include_r_tol=include_r_tol,
            treatment_n_levels=treatment_n_levels,
        )
        return out_path
    except Exception as exc:
        logger.warning(f"Failed to export PestCNC.OUT in {run_dir}: {exc}")
        if raise_on_error:
            raise
        return None


def wrap_dssat_execution(
    runner_func: Callable[..., Any],
    run_dir: Union[str, Path],
    *args: Any,
    cnc_a: float = DEFAULT_CNC_A,
    cnc_b: float = DEFAULT_CNC_B,
    cnc_w0: float = DEFAULT_CNC_W0,
    cnc_nc_inf: float = DEFAULT_CNC_NC_INF,
    include_r_tol: bool = False,
    treatment_n_levels: Optional[Any] = None,
    **kwargs: Any,
) -> Any:
    """Wrap a DSSAT run invocation to automatically post-process CNC outputs.

    Non-destructive wrapper: calls runner_func(*args, **kwargs),
    then triggers post_process_dssat_cnc(run_dir).
    """
    result = runner_func(*args, **kwargs)
    post_process_dssat_cnc(
        run_dir,
        cnc_a=cnc_a,
        cnc_b=cnc_b,
        cnc_w0=cnc_w0,
        cnc_nc_inf=cnc_nc_inf,
        include_r_tol=include_r_tol,
        treatment_n_levels=treatment_n_levels,
    )
    return result
