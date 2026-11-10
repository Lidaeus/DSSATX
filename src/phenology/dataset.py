"""
src/phenology/dataset.py
========================
Multi-season benchmark dataset loader and tensor bundle generator for
Neural-Phenology modeling in protected greenhouse crops.

Provides:
- load_benchmark_dataset(dataset_dir): Loads relational DataFrames
- get_seasonal_tensor_bundle(dataset_dir, device): Returns batched PyTorch tensors

Author: teamwork_preview_worker_m1
Date: 2026-09-20
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd
import torch


def _find_project_root() -> Path:
    """Locates the project root directory containing the data/ directory."""
    curr = Path(__file__).resolve().parent
    for p in [curr, curr.parent, curr.parent.parent]:
        if (p / "data").exists():
            return p
    return Path.cwd()


def load_benchmark_dataset(
    dataset_dir: Union[str, Path] = "data/benchmark/phenology"
) -> Dict[str, pd.DataFrame]:
    """
    Loads all 4 Milestone 1 benchmark dataset tables into a dictionary of pandas DataFrames.

    Parameters
    ----------
    dataset_dir : str or Path
        Directory containing the benchmark CSV files. If relative, resolved against project root.

    Returns
    -------
    dict[str, pd.DataFrame]
        Dictionary with keys:
        - 'metadata': treatment_season_metadata.csv (35 treatments across 3 seasons)
        - 'microclimate': microclimate_daily_series.csv (564 continuous days)
        - 'targets': phenology_benchmark_targets.csv (Ground truth milestone targets)
        - 'literature': literature_solanaceous_benchmarks.csv (8 classic literature benchmarks)
    """
    path = Path(dataset_dir)
    if not path.is_absolute():
        project_root = _find_project_root()
        path = (project_root / path).resolve()

    metadata_path = path / "treatment_season_metadata.csv"
    microclimate_path = path / "microclimate_daily_series.csv"
    targets_path = path / "phenology_benchmark_targets.csv"
    literature_path = path / "literature_solanaceous_benchmarks.csv"

    for file_p in [metadata_path, microclimate_path, targets_path, literature_path]:
        if not file_p.exists():
            raise FileNotFoundError(
                f"Benchmark file not found at: {file_p}. "
                f"Please run 'python tools/build_phenology_benchmark.py' first."
            )

    metadata_df = pd.read_csv(metadata_path)
    microclimate_df = pd.read_csv(microclimate_path)
    targets_df = pd.read_csv(targets_path)
    literature_df = pd.read_csv(literature_path)

    return {
        "metadata": metadata_df,
        "microclimate": microclimate_df,
        "targets": targets_df,
        "literature": literature_df,
    }


def get_seasonal_tensor_bundle(
    dataset_dir: Union[str, Path] = "data/benchmark/phenology",
    device: Optional[torch.device] = None,
    par_factor: float = 2.05,
) -> Dict[str, Dict[str, Any]]:
    """
    Converts microclimate series, treatment variables, and target milestones
    into clean PyTorch tensors ready for batch processing in NeuralPhenologyOperator.

    Parameters
    ----------
    dataset_dir : str or Path
        Directory containing the benchmark CSV files.
    device : torch.device, optional
        Target PyTorch device (CPU or CUDA).
    par_factor : float, default 2.05
        Multiplier converting solar radiation (MJ/m2/d) to PAR Daily Light Integral (mol/m2/d).

    Returns
    -------
    dict[str, dict[str, Any]]
        Top-level dictionary keyed by season ID: '25SP', '26SP', '25FA'.
        Each seasonal dictionary contains:
        - 'season_id': str
        - 'batch_size': int (number of treatments B)
        - 'seq_len': int (number of season days T)
        - 'tavg': Tensor (B, T) float32 - Daily mean temperature (C)
        - 'tmin': Tensor (B, T) float32 - Daily minimum temperature (C)
        - 'tmax': Tensor (B, T) float32 - Daily maximum temperature (C)
        - 'dif': Tensor (B, T) float32 - Diurnal temperature difference Tmax - Tmin (C)
        - 'srad': Tensor (B, T) float32 - Daily solar radiation (MJ/m2)
        - 'dli': Tensor (B, T) float32 - Daily light integral (mol/m2/d)
        - 'daylength': Tensor (B, T) float32 - Astronomical daylength (hr)
        - 'rhum': Tensor (B, T) float32 - Relative humidity (%)
        - 'chilling': Tensor (B, T) float32 - Daily chilling exposure max(0, 10 - Tmin)
        - 'page': Tensor (B,) float32 - Nursery seedling age (days, 22.0)
        - 'irrigation_coeff': Tensor (B,) float32 - Irrigation multiplier (1.2, 0.8, 0.4, 1.0)
        - 'n_rate_kg_ha': Tensor (B,) float32 - Applied nitrogen rate (kg N/ha)
        - 'treatment': Tensor (B,) int64 - Treatment IDs
        - 'treatment_label': list[str] - Treatment labels (e.g. 'TN2 (W3-N3)')
        - 'dataset_role': list[str] - Data roles ('calibration', 'validation', 'blind_test')
        - 'targets': dict[str, Tensor] - Milestone targets (B,) in DAP (e.g. ADAPS, PDFPS, cessation)
        - 'target_uncertainties': dict[str, Tensor] - Milestone measurement standard errors (B,)
        - 'milestone_stages': dict[str, float] - Target developmental stage index D (0.0 to 2.5)
        - 'dates': list[str] - Calendar dates for the season (length T)
        - 'doy': Tensor (T,) int64 - Day of year sequence
    """
    tables = load_benchmark_dataset(dataset_dir)
    metadata = tables["metadata"]
    microclimate = tables["microclimate"]
    targets = tables["targets"]

    # Defined season calendar windows (transplant date to season harvest/pulling conclusion)
    season_windows = {
        "25SP": {"start": "2025-03-16", "end": "2025-07-17"},  # DOY 75 to 198 (124 days)
        "26SP": {"start": "2026-03-16", "end": "2026-07-17"},  # DOY 75 to 198 (124 days)
        "25FA": {"start": "2025-08-13", "end": "2026-01-10"},  # DOY 225 to 2026-01-10 (151 days)
    }

    bundle: Dict[str, Dict[str, Any]] = {}

    for season_id, win in season_windows.items():
        # 1. Filter treatments for this season
        season_meta = metadata[metadata["season_id"] == season_id].sort_values(by="treatment").reset_index(drop=True)
        b_size = len(season_meta)
        if b_size == 0:
            continue

        # 2. Filter microclimate for this season
        start_date = win["start"]
        end_date = win["end"]
        season_weather = microclimate[
            (microclimate["date"] >= start_date) & (microclimate["date"] <= end_date)
        ].sort_values(by="date").reset_index(drop=True)
        t_len = len(season_weather)

        # 3. Base 1D time series
        tavg_1d = torch.tensor(season_weather["tavg_c"].values, dtype=torch.float32)
        tmin_1d = torch.tensor(season_weather["tmin_c"].values, dtype=torch.float32)
        tmax_1d = torch.tensor(season_weather["tmax_c"].values, dtype=torch.float32)
        dif_1d = torch.tensor(season_weather["dif_c"].values, dtype=torch.float32)
        srad_1d = torch.tensor(season_weather["srad_mj_m2"].values, dtype=torch.float32)
        rhum_1d = torch.tensor(season_weather["rhum_pct"].values, dtype=torch.float32)
        daylength_1d = torch.tensor(season_weather["daylength_hr"].values, dtype=torch.float32)
        chilling_1d = torch.tensor(season_weather["chilling_exposure_10c"].values, dtype=torch.float32)
        dli_1d = srad_1d * par_factor

        # 4. Broadcast to shape (B, T)
        tavg = tavg_1d.unsqueeze(0).expand(b_size, t_len).clone()
        tmin = tmin_1d.unsqueeze(0).expand(b_size, t_len).clone()
        tmax = tmax_1d.unsqueeze(0).expand(b_size, t_len).clone()
        dif = dif_1d.unsqueeze(0).expand(b_size, t_len).clone()
        srad = srad_1d.unsqueeze(0).expand(b_size, t_len).clone()
        dli = dli_1d.unsqueeze(0).expand(b_size, t_len).clone()
        daylength = daylength_1d.unsqueeze(0).expand(b_size, t_len).clone()
        rhum = rhum_1d.unsqueeze(0).expand(b_size, t_len).clone()
        chilling = chilling_1d.unsqueeze(0).expand(b_size, t_len).clone()

        # 5. Treatment-level attributes (B,)
        page = torch.tensor(season_meta["seedling_age_days"].values, dtype=torch.float32)
        irrigation_coeff = torch.tensor(season_meta["irrigation_coeff"].values, dtype=torch.float32)
        n_rate_kg_ha = torch.tensor(season_meta["n_rate_kg_ha"].values, dtype=torch.float32)
        treatment_tensor = torch.tensor(season_meta["treatment"].values, dtype=torch.int64)
        treatment_labels = list(season_meta["treatment_label"].values)
        dataset_roles = list(season_meta["dataset_role"].values)

        # 6. Extract milestone targets
        season_targets = targets[targets["season_id"] == season_id]
        target_dict: Dict[str, torch.Tensor] = {}
        target_se_dict: Dict[str, torch.Tensor] = {}
        target_stage_dict: Dict[str, float] = {}

        events = ["transplanting", "anthesis", "fruit_set", "first_harvest", "peak_harvest", "cessation"]
        for ev in events:
            ev_sub = season_targets[season_targets["event_type"] == ev]
            val_map = dict(zip(ev_sub["treatment"], ev_sub["observed_value"]))
            se_map = dict(zip(ev_sub["treatment"], ev_sub["uncertainty_se"]))
            stage_idx = float(ev_sub["target_stage_index"].iloc[0]) if len(ev_sub) > 0 else 0.0

            vals = [val_map.get(t, 0.0) for t in season_meta["treatment"]]
            ses = [se_map.get(t, 1.0) for t in season_meta["treatment"]]

            target_dict[ev] = torch.tensor(vals, dtype=torch.float32)
            target_se_dict[ev] = torch.tensor(ses, dtype=torch.float32)
            target_stage_dict[ev] = stage_idx

        # Canonical uppercase aliases for loss functions and optimization
        target_dict["ADAPS"] = target_dict["anthesis"]
        target_dict["PDFPS"] = target_dict["fruit_set"]
        target_dict["CESSATION"] = target_dict["cessation"]
        target_se_dict["ADAPS"] = target_se_dict["anthesis"]
        target_se_dict["PDFPS"] = target_se_dict["fruit_set"]
        target_se_dict["CESSATION"] = target_se_dict["cessation"]
        target_stage_dict["ADAPS"] = 1.00
        target_stage_dict["PDFPS"] = 1.25
        target_stage_dict["CESSATION"] = 2.50

        doy = torch.tensor(season_weather["doy"].values, dtype=torch.int64)

        # Move tensors to target device if specified
        if device is not None:
            tavg = tavg.to(device)
            tmin = tmin.to(device)
            tmax = tmax.to(device)
            dif = dif.to(device)
            srad = srad.to(device)
            dli = dli.to(device)
            daylength = daylength.to(device)
            rhum = rhum.to(device)
            chilling = chilling.to(device)
            page = page.to(device)
            irrigation_coeff = irrigation_coeff.to(device)
            n_rate_kg_ha = n_rate_kg_ha.to(device)
            treatment_tensor = treatment_tensor.to(device)
            doy = doy.to(device)
            for k in target_dict:
                target_dict[k] = target_dict[k].to(device)
                target_se_dict[k] = target_se_dict[k].to(device)

        bundle[season_id] = {
            "season_id": season_id,
            "batch_size": b_size,
            "seq_len": t_len,
            "tavg": tavg,
            "tmin": tmin,
            "tmax": tmax,
            "dif": dif,
            "srad": srad,
            "dli": dli,
            "daylength": daylength,
            "rhum": rhum,
            "chilling": chilling,
            "page": page,
            "irrigation_coeff": irrigation_coeff,
            "n_rate_kg_ha": n_rate_kg_ha,
            "treatment": treatment_tensor,
            "treatment_label": treatment_labels,
            "dataset_role": dataset_roles,
            "targets": target_dict,
            "target_uncertainties": target_se_dict,
            "milestone_stages": target_stage_dict,
            "dates": list(season_weather["date"].values),
            "doy": doy,
        }

    return bundle
