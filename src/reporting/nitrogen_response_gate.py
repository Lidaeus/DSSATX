"""Deterministic nitrogen-response gates for calibrated yield candidates."""

from __future__ import annotations

import math

import pandas as pd


def mean_n2_n1_minus_n0_gate(
    harvest: pd.DataFrame,
    mapping: pd.DataFrame,
    season_id: str,
) -> dict[str, object]:
    """Evaluate the mean of N2-N0 and N1-N0 terminal fresh-yield contrasts.

    The mean is formed from every water stratum in ``season_id`` that has all
    three nitrogen levels.  N3 is deliberately excluded.  Terminal rows are
    selected per treatment, so differing harvest counts cannot misalign the
    treatment comparison.
    """

    h = harvest.copy()
    m = mapping.loc[mapping["season_id"].astype(str).eq(str(season_id))].copy()
    if h.empty or m.empty:
        raise ValueError(f"missing harvest or mapping data for {season_id}")
    h["TN"] = pd.to_numeric(h["TN"], errors="raise").astype(int)
    m["treatment"] = pd.to_numeric(m["treatment"], errors="raise").astype(int)
    terminal = h.sort_values(["TN", "DATE", "HNO"]).groupby("TN", as_index=False).tail(1)
    terminal = terminal.merge(
        m[["treatment", "water_level", "nitrogen_level"]],
        left_on="TN",
        right_on="treatment",
        how="inner",
        validate="one_to_one",
    )
    records: list[dict[str, object]] = []
    for water, group in terminal.groupby("water_level", sort=True):
        by_n = group.set_index("nitrogen_level")
        if not {"N0", "N1", "N2"}.issubset(by_n.index):
            continue
        for level in ("N2", "N1"):
            obs = float(by_n.loc[level, "OBS_FRESH_CUM"] - by_n.loc["N0", "OBS_FRESH_CUM"])
            sim = float(by_n.loc[level, "SIM_FRESH_CUM"] - by_n.loc["N0", "SIM_FRESH_CUM"])
            records.append(
                {"season_id": season_id, "water_level": water, "contrast": f"{level}-N0", "observed": obs, "simulated": sim}
            )
    if not records:
        raise ValueError(f"no complete N2/N1/N0 water stratum for {season_id}")
    obs_mean = sum(float(row["observed"]) for row in records) / len(records)
    sim_mean = sum(float(row["simulated"]) for row in records) / len(records)
    return {
        "season_id": season_id,
        "contrast_definition": "mean_of_N2_minus_N0_and_N1_minus_N0",
        "n_contrasts": len(records),
        "observed_mean": obs_mean,
        "simulated_mean": sim_mean,
        "absolute_error": abs(sim_mean - obs_mean),
        "direction_pass": bool(math.isfinite(sim_mean) and sim_mean > 0.0),
        "records": records,
    }
