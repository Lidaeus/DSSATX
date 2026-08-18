"""Report member-126 N/W response metrics after the 26SP T12 IC update."""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.calibration.nitrogen_response import (
    load_n_response_mapping,
    write_simulated_n_response,
    write_simulated_water_response,
)


CASE = "e02_fixedsoil_nse_official_25sp26sp_200x6_20260817"
RUN_DIR = ROOT / "workspace/runs" / CASE
DET_ROOT = RUN_DIR / "deterministic_candidates/phi_q10_highest_nse_26sp_t12_ic_20260818"
FIG_ROOT = ROOT / "figture/member126_two_season_full_20260817"
MAPPING_CSV = ROOT / "configs/runs/e02_v2_25sp26sp_water_n_mapping_20260808.csv"
REGISTRY_CSV = RUN_DIR / f"{CASE}_observation_registry.csv"
RUN_MAPPING_CSV = DET_ROOT / "best126_det_official_run_mapping.csv"
TAGGED = re.compile(
    r"^RUN\s+(?P<run>\d+)\s+TN\s+(?P<tn>\d+)\s+"
    r"@HNO@\s+(?P<hno>\d+)\s+DATE\s+(?P<date>\d+)\s+"
    r"@(?P<token>[NW]RESPS)@\s+(?P<sim>[-+0-9.eE]+)"
)


def metric_values(obs: np.ndarray, sim: np.ndarray) -> dict[str, float | int]:
    residual = sim - obs
    sst = float(np.square(obs - obs.mean()).sum())
    nse = 1.0 - float(np.square(residual).sum()) / sst if sst > 0 else math.nan
    obs_dev = obs - obs.mean()
    denominator = float(np.square(np.abs(sim - obs.mean()) + np.abs(obs_dev)).sum())
    d_index = 1.0 - float(np.square(residual).sum()) / denominator if denominator > 0 else math.nan
    return {
        "n": len(obs),
        "nse": nse,
        "rmse": float(np.sqrt(np.mean(np.square(residual)))),
        "mae": float(np.mean(np.abs(residual))),
        "bias_sim_minus_obs": float(np.mean(residual)),
        "pbias_pct": float(100.0 * residual.sum() / obs.sum()) if obs.sum() else math.nan,
        "r2": float(np.corrcoef(obs, sim)[0, 1] ** 2) if len(obs) > 1 else math.nan,
        "d_index": d_index,
        "observed_mean": float(obs.mean()),
        "simulated_mean": float(sim.mean()),
        "observed_sd": float(obs.std(ddof=1)),
        "simulated_sd": float(sim.std(ddof=1)),
    }


def parse_simulated(path: Path, family: str) -> pd.DataFrame:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = TAGGED.match(line)
        if match:
            rows.append({
                "family": family,
                "global_run": int(match.group("run")),
                "treatment": int(match.group("tn")),
                "harvest_number": int(match.group("hno")),
                "date": int(match.group("date")),
                "simulated": float(match.group("sim")),
            })
    return pd.DataFrame(rows)


def main() -> int:
    run_mapping = pd.read_csv(RUN_MAPPING_CSV).to_dict("records")
    mapping = load_n_response_mapping(MAPPING_CSV, run_mapping, response_levels=("N1", "N2"))
    n_out = write_simulated_n_response(
        DET_ROOT / "PestHarvest.OUT", DET_ROOT / "PestNResponse.OUT", mapping,
        response_levels=("N1", "N2"), source_scale="raw",
        contrast_scale="raw_difference", harvest_scope="all",
    )
    w_out = write_simulated_water_response(
        DET_ROOT / "PestHarvest.OUT", DET_ROOT / "PestWResponse.OUT", mapping,
        source_scale="raw", contrast_scale="raw_difference", harvest_scope="all",
        high_water="W2", low_water="W1",
    )
    simulated = pd.concat([
        parse_simulated(n_out, "N_RESPONSE"),
        parse_simulated(w_out, "W_RESPONSE"),
    ], ignore_index=True)

    registry = pd.read_csv(REGISTRY_CSV, encoding="utf-8-sig")
    registry = registry[registry["sim_token"].isin(["NRESPS", "WRESPS"])].copy()
    registry["family"] = registry["sim_token"].map({"NRESPS": "N_RESPONSE", "WRESPS": "W_RESPONSE"})
    registry["harvest_number"] = registry["obsnme"].str.extract(r"_H(\d+)$").astype(int)
    observed = registry.rename(columns={
        "season_id": "season", "raw_obsval": "observed",
    })[["family", "season", "global_run", "treatment", "harvest_number", "observed"]]
    pairs = observed.merge(
        simulated,
        on=["family", "global_run", "treatment", "harvest_number"],
        how="left", validate="one_to_one",
    )
    if pairs["simulated"].isna().any():
        raise ValueError("missing simulated response values after registry join")
    if len(pairs) != 100:
        raise ValueError(f"expected 100 response pairs, got {len(pairs)}")

    metrics: list[dict] = []
    for (family, season), part in pairs.groupby(["family", "season"], sort=True):
        values = metric_values(part["observed"].to_numpy(float), part["simulated"].to_numpy(float))
        metrics.append({"family": family, "season": season, **values})
    metrics_frame = pd.DataFrame(metrics)
    pairs.to_csv(FIG_ROOT / "nw_response_pairs.csv", index=False, encoding="utf-8-sig")
    metrics_frame.to_csv(FIG_ROOT / "nw_response_metrics.csv", index=False, encoding="utf-8-sig")
    summary = {
        "candidate": "member126",
        "deterministic_root": str(DET_ROOT),
        "response_definitions": {
            "N_RESPONSE": "raw CHPDT difference: N1/N2 minus N0 within water level",
            "W_RESPONSE": "raw CHPDT difference: W2 minus W1 within nitrogen level",
        },
        "sst_scope": "calculated separately for each season x response family",
        "pairs": len(pairs),
        "metrics": metrics,
    }
    (FIG_ROOT / "nw_response_metrics.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(metrics_frame.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
