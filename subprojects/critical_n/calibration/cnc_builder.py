"""Calibration task builder extension for Critical Nitrogen Dilution (Scheme A).

Implements:
1. Sparse phenological subsampling (3~5 key dates per treatment) to avoid
   collinear redundancy (corr(NNI, CWAD) = 0.9538) while keeping TSVD well-conditioned.
2. Standard observation weighting (w in [0.05, 0.50] or group policy [0.50, 1.25]).
3. Observation group registration: 'cnc_nni'.
4. PyEMU Pst extension helper for seamless, non-destructive PEST task assembly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import pandas as pd

from subprojects.critical_n.adapters.instruction_generator import (
    CNCObservationTarget,
    generate_pest_cnc_instructions,
    make_obs_name,
)
from subprojects.critical_n.adapters.stream_parser import (
    DailyMergedRecord,
    load_merged_nitrogen_series,
)
from subprojects.critical_n.core.objective_penalty import (
    DEFAULT_GROUP_POLICY_WEIGHT,
    DEFAULT_VARIANCE_NORMALIZED_WEIGHT,
    PHYSIOLOGICAL_NNI_INTERVALS,
)

# Standard target NNI centers by nitrogen level
STANDARD_TARGET_NNI: dict[str, float] = {
    "N0": 0.55,  # Center of [0.40, 0.70]
    "N1": 0.85,  # Center of [0.70, 1.00]
    "N2": 1.00,  # Center of [0.85, 1.15]
    "N3": 1.10,  # Center of [1.00, 1.30]
}


def select_phenological_subsampling_dates(
    records: Sequence[DailyMergedRecord],
    n_points: int = 4,
    min_biomass_t_ha: float = 0.05,
) -> list[int]:
    """Select 3~5 key phenological stage DAS indices from a simulation trajectory.

    Filters out pre-emergence steps (CWAD < 50 kg/ha), then divides the growth
    season into approximately equal phenological intervals:
    1. Early vegetative / canopy closure start (~25% of season)
    2. Flowering / initial fruit set (~50% of season)
    3. Peak harvest / mid reproductive load (~75% of season)
    4. Final harvest / season end (100% of season)
    """
    if n_points <= 0:
        return []

    valid_recs = [r for r in records if (r.cwad / 1000.0) >= min_biomass_t_ha]
    if not valid_recs:
        return []

    if n_points == 1:
        return [valid_recs[-1].das]

    if len(valid_recs) <= n_points:
        return [r.das for r in valid_recs]

    # Pick spaced indices
    selected_das: list[int] = []
    step = (len(valid_recs) - 1) / float(n_points - 1)
    for i in range(n_points):
        idx = int(round(i * step))
        selected_das.append(valid_recs[idx].das)

    return sorted(list(set(selected_das)))


def resolve_treatment_n_levels(
    run_dir: Union[str, Path],
    treatment_n_levels: Optional[Union[Mapping[int, str], str, Path, pd.DataFrame]] = None,
) -> dict[int, str]:
    """Resolve treatment -> nitrogen level mapping from dict, DataFrame, or metadata CSV."""
    if isinstance(treatment_n_levels, pd.DataFrame):
        if "treatment" in treatment_n_levels.columns and "nitrogen_level" in treatment_n_levels.columns:
            return dict(zip(treatment_n_levels["treatment"].astype(int), treatment_n_levels["nitrogen_level"].astype(str)))
        return {}

    if isinstance(treatment_n_levels, (str, Path)):
        p = Path(treatment_n_levels)
        if p.is_file():
            df = pd.read_csv(p)
            if "treatment" in df.columns and "nitrogen_level" in df.columns:
                return dict(zip(df["treatment"].astype(int), df["nitrogen_level"].astype(str)))
        return {}

    if isinstance(treatment_n_levels, Mapping):
        return {int(k): str(v) for k, v in treatment_n_levels.items()}

    # Auto-discover if None
    dir_path = Path(run_dir)
    candidates = [
        dir_path / "treatment_metadata.csv",
        Path("configs/figures/treatment_metadata_xxql2501.csv"),
    ]
    for cand in candidates:
        if cand.is_file():
            try:
                df = pd.read_csv(cand)
                if "treatment" in df.columns and "nitrogen_level" in df.columns:
                    return dict(zip(df["treatment"].astype(int), df["nitrogen_level"].astype(str)))
            except Exception:
                pass

    return {}


def build_cnc_observation_targets(
    run_dir: Union[str, Path],
    treatment_n_levels: Optional[Union[Mapping[int, str], str, Path, pd.DataFrame]] = None,
    n_points_per_treatment: int = 4,
    weight: float = DEFAULT_VARIANCE_NORMALIZED_WEIGHT,
    group_name: str = "cnc_nni",
    use_relaxation: bool = True,
    strict_treatment_mapping: bool = True,
) -> list[CNCObservationTarget]:
    """Build sparse CNC observation targets for all treatments in run_dir.

    Parameters
    ----------
    run_dir : Path or str
        DSSAT run directory.
    treatment_n_levels : Mapping[int, str], str, Path, or DataFrame, optional
        Dict or metadata CSV mapping treatment_id -> nitrogen level ('N0', 'N1', 'N2', 'N3').
        If None, attempts auto-discovery from treatment_metadata.csv.
    n_points_per_treatment : int, optional
        Number of phenological subsampling dates per treatment, default 4 (3~5 range).
    weight : float, optional
        PEST observation weight w, default 0.25 (range [0.05, 0.50]).
    group_name : str, optional
        PEST observation group name, default 'cnc_nni'.
    use_relaxation : bool, optional
        If True (default for R0), implements zero-residual one-sided relaxation projection
        operator: targets R_TOL with target_value = 0.000000. Within physiological tolerance
        intervals (e.g. [1.00, 1.30] for N3 luxury, [0.40, 0.70] for N0 deficit), residual
        is exactly 0.000000.
        If False, targets NNI with fixed center point values.
    strict_treatment_mapping : bool, optional
        If True (default for R0), raises ValueError if a treatment has no N level mapping,
        prohibiting silent fallback to 'N2'.

    Returns
    -------
    list[CNCObservationTarget]
        List of targets ready for instruction generation and PEST control file injection.
    """
    dir_path = Path(run_dir)
    runs_data = load_merged_nitrogen_series(dir_path)
    n_map = resolve_treatment_n_levels(dir_path, treatment_n_levels)

    targets: list[CNCObservationTarget] = []

    for run_id in sorted(runs_data.keys()):
        recs = runs_data[run_id]
        if not recs:
            continue
        trt_id = recs[0].treatment_id

        if trt_id not in n_map:
            if strict_treatment_mapping:
                raise ValueError(
                    f"Treatment {trt_id} has no nitrogen level mapping in {n_map}. "
                    f"Silent fallback to 'N2' is prohibited by R0 protocol."
                )
            n_level = "N2"
        else:
            n_level = n_map[trt_id]

        chosen_das = select_phenological_subsampling_dates(
            recs, n_points=n_points_per_treatment
        )

        for das in chosen_das:
            obs_name = make_obs_name(trt_id, das)
            if use_relaxation:
                target_val = 0.0
                obs_var = "R_TOL"
            else:
                target_val = STANDARD_TARGET_NNI.get(n_level, 1.00)
                obs_var = "NNI"

            targets.append(
                CNCObservationTarget(
                    obs_name=obs_name,
                    run_id=run_id,
                    treatment_id=trt_id,
                    das=das,
                    variable=obs_var,
                    target_value=target_val,
                    weight=weight,
                    group=group_name,
                )
            )

    return targets


def attach_cnc_to_pst(
    pst: Any,  # pyemu.Pst
    targets: Sequence[CNCObservationTarget],
    model_output_file: str = "PestCNC.OUT",
    instruction_file: str = "PestCNC.OUT.ins",
) -> Any:
    """Non-destructively register CNC targets and files into a pyemu.Pst instance.

    Parameters
    ----------
    pst : pyemu.Pst
        Active PEST control file object.
    targets : Sequence[CNCObservationTarget]
        List of CNC targets to add.
    model_output_file : str
        Relative path to PestCNC.OUT.
    instruction_file : str
        Relative path to PestCNC.OUT.ins.

    Returns
    -------
    pyemu.Pst
        Updated Pst object with new observations and instruction file registered.
    """
    import pyemu

    # Add instruction file pair if not present
    ins_files = list(pst.instruction_files)
    if instruction_file not in ins_files:
        new_io_row = pd.DataFrame([{"pest_file": instruction_file, "model_file": model_output_file}])
        if hasattr(pst, "model_output_data") and isinstance(pst.model_output_data, pd.DataFrame):
            pst.model_output_data = pd.concat([pst.model_output_data, new_io_row], ignore_index=True)
        else:
            try:
                pst.instruction_files.append(instruction_file)
                pst.output_files.append(model_output_file)
            except Exception:
                pass

    # Build new observation DataFrame rows
    new_rows = []
    for t in targets:
        if t.obs_name in pst.observation_data.index:
            continue
        new_rows.append(
            {
                "obsnme": t.obs_name,
                "obsval": t.target_value,
                "weight": t.weight,
                "obgnme": t.group,
            }
        )

    if new_rows:
        new_df = pd.DataFrame(new_rows)
        new_df.index = new_df["obsnme"]
        # Merge with existing observation data
        pst.observation_data = pd.concat([pst.observation_data, new_df])

    return pst
