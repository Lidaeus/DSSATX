"""Quantify monotonicity conflicts in the observed N-response contract.

For each season, water stratum and harvest, the observed fresh-yield
contrasts N1/N2/N3 minus N0 are compared with the physically expected
non-decreasing sequence.  Isotonic regression gives a descriptive lower
bound on error for any monotone model; it is not used to alter Phi or data.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def pava(y: np.ndarray) -> np.ndarray:
    """Least-squares non-decreasing fit (pool-adjacent-violators)."""
    means: list[float] = []
    counts: list[int] = []
    for value in y.astype(float):
        means.append(float(value)); counts.append(1)
        while len(means) >= 2 and means[-2] > means[-1]:
            n = counts[-2] + counts[-1]
            means[-2] = (counts[-2] * means[-2] + counts[-1] * means[-1]) / n
            counts[-2] = n
            means.pop(); counts.pop()
    out: list[float] = []
    for mean, count in zip(means, counts):
        out.extend([mean] * count)
    return np.asarray(out, dtype=float)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--replay-root", type=Path, required=True)
    p.add_argument("--mapping-csv", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()
    root = args.replay_root.resolve()
    out = args.out_dir.resolve(); out.mkdir(parents=True, exist_ok=True)
    meta = pd.read_csv(args.mapping_csv.resolve())
    all_rows: list[dict[str, object]] = []
    for season in ("25SP", "26SP"):
        sd = root / "_seasons" / season
        hpath = sd / f"{season}_deterministic_harvest_compare.csv"
        h = pd.read_csv(hpath)
        m = meta[meta["season_id"].eq(season)].set_index("treatment")
        h = h.merge(m[["water_level", "nitrogen_level"]], left_on="TN", right_index=True, how="left")
        for (hno, water), g in h.groupby(["HNO", "water_level"], sort=True):
            byn = g.set_index("nitrogen_level")
            if "N0" not in byn.index:
                continue
            for lev in ("N1", "N2", "N3"):
                if lev not in byn.index:
                    continue
                all_rows.append({
                    "season": season, "HNO": int(hno), "water": str(water), "level": lev,
                    "obs": float(byn.loc[lev, "OBS_FRESH_CUM"] - byn.loc["N0", "OBS_FRESH_CUM"]),
                    "sim": float(byn.loc[lev, "SIM_FRESH_CUM"] - byn.loc["N0", "SIM_FRESH_CUM"]),
                })
    d = pd.DataFrame(all_rows)
    rows: list[dict[str, object]] = []
    for (season, hno, water), g in d.groupby(["season", "HNO", "water"], sort=True):
        g = g.set_index("level").reindex(["N1", "N2", "N3"]).dropna(subset=["obs", "sim"])
        if len(g) < 2:
            continue
        obs = g["obs"].to_numpy(float); sim = g["sim"].to_numpy(float)
        iso = pava(obs)
        obs_mae = float(np.mean(np.abs(obs)))
        sim_mae = float(np.mean(np.abs(sim - obs)))
        iso_mae = float(np.mean(np.abs(iso - obs)))
        rows.append({
            "season": season, "HNO": int(hno), "water": water,
            "levels_present": "|".join(g.index),
            "obs_N1": obs[0], "obs_N2": obs[1] if len(obs) > 1 else np.nan, "obs_N3": obs[2] if len(obs) > 2 else np.nan,
            "sim_N1": sim[0], "sim_N2": sim[1] if len(sim) > 1 else np.nan, "sim_N3": sim[2] if len(sim) > 2 else np.nan,
            "iso_N1": iso[0], "iso_N2": iso[1] if len(iso) > 1 else np.nan, "iso_N3": iso[2] if len(iso) > 2 else np.nan,
            "obs_order_violations": int(sum(obs[i] > obs[i + 1] for i in range(len(obs) - 1))),
            "obs_monotonic": bool(np.all(np.diff(obs) >= 0)),
            "sim_monotonic": bool(np.all(np.diff(sim) >= 0)),
            "sim_mae": sim_mae,
            "monotone_l2_bound_mae": iso_mae,
            "monotone_l2_bound_rmse": float(np.sqrt(np.mean((iso - obs) ** 2))),
        })
    score = pd.DataFrame(rows)
    score.to_csv(out / "nresponse_monotonicity_by_layer.csv", index=False, encoding="utf-8-sig")
    summary = []
    for season, g in score.groupby("season"):
        summary.append({
            "season": season, "layers": int(len(g)),
            "observed_nonmonotone_layers": int((~g.obs_monotonic).sum()),
            "simulated_nonmonotone_layers": int((~g.sim_monotonic).sum()),
            "observed_violation_pairs": int(g.obs_order_violations.sum()),
            "mean_sim_mae": float(g.sim_mae.mean()),
            "mean_monotone_l2_bound_mae": float(g.monotone_l2_bound_mae.mean()),
        })
    pd.DataFrame(summary).to_csv(out / "nresponse_monotonicity_summary.csv", index=False, encoding="utf-8-sig")
    audit = {"scope": "best71 S0-3A deterministic harvest contrasts", "layers": int(len(score)), "summary": summary, "data_modified": False, "phi_modified": False}
    (out / "nresponse_feasibility_audit.json").write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
