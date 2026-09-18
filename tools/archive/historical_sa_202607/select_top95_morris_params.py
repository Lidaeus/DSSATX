"""Select the smallest parameter set explaining 95% of normalized Morris effect.

The ranking is computed after Morris completion from all available seasons and
seeds. Effects are normalized within each response before averaging, so yield,
canopy, and organ-N outputs cannot dominate solely because of units.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-root", type=Path, required=True)
    ap.add_argument("--case-dir", type=Path, action="append", default=[],
                    help="Explicit validated case directory; may be repeated")
    ap.add_argument("--allow-degenerate-feature", action="append", default=["FRUIT_N_END"],
                    help="Sparse response feature to exclude when every effect is zero")
    ap.add_argument("--exclude-parameter", action="append", default=[],
                    help="Parameter excluded from the calibration selection (e.g. nuisance soil/IC)")
    ap.add_argument("--bounds", type=Path, required=True)
    ap.add_argument("--out-ranking", type=Path, required=True)
    ap.add_argument("--out-bounds", type=Path, required=True)
    args = ap.parse_args()
    mio = [path / "sa_sen_morris.mio" for path in args.case_dir]
    if not mio:
        mio = sorted(args.run_root.glob("*/seed_*/sa_sen_morris.mio"))
    if len(mio) < 2:
        raise SystemExit(f"need at least two completed Morris cases, found {len(mio)}")
    frames = []
    for path in mio:
        frame = pd.read_csv(path)
        required = {"observation_name", "parameter_name", "sen_mean_abs"}
        if not required.issubset(frame.columns):
            raise ValueError(f"missing columns in {path}: {required - set(frame.columns)}")
        frame["parameter"] = frame["parameter_name"].astype(str).str.upper()
        frame["observation"] = frame["observation_name"].astype(str).str.lower()
        frame["score"] = pd.to_numeric(frame["sen_mean_abs"], errors="coerce")
        if frame["score"].isna().any() or (frame["score"] < 0).any():
            raise ValueError(f"non-finite/negative Morris effects in {path}")
        totals = frame.groupby("observation")["score"].transform("sum")
        degenerate = frame.loc[totals <= 0, "observation"].astype(str)
        allowed = {str(value).upper() for value in args.allow_degenerate_feature}
        degenerate_features = {name.split("_", 1)[1].upper() for name in degenerate if "_" in name}
        if (degenerate_features - allowed):
            bad = sorted(frame.loc[totals <= 0, "observation"].unique())
            raise ValueError(f"degenerate responses remain in {path}: {bad[:8]}")
        if not degenerate.empty:
            frame = frame.loc[~frame["observation"].isin(set(degenerate))].copy()
            totals = frame.groupby("observation")["score"].transform("sum")
        frame["relative_effect"] = frame["score"] / totals
        frame["case"] = str(path.parent)
        frames.append(frame[["case", "observation", "parameter", "relative_effect"]])
    all_effects = pd.concat(frames, ignore_index=True)
    ranking = (all_effects.groupby("parameter", as_index=False)["relative_effect"].mean()
               .rename(columns={"relative_effect": "mean_normalized_effect"})
               .sort_values(["mean_normalized_effect", "parameter"], ascending=[False, True], kind="stable")
               .reset_index(drop=True))
    excluded = {str(value).upper() for value in args.exclude_parameter}
    if excluded:
        ranking = ranking.loc[~ranking["parameter"].isin(excluded)].reset_index(drop=True)
    ranking["cumulative_effect"] = ranking["mean_normalized_effect"].cumsum()
    total = ranking["mean_normalized_effect"].sum()
    ranking["cumulative_fraction"] = ranking["cumulative_effect"] / total
    ranking["selected_top95"] = ranking["cumulative_fraction"] - ranking["mean_normalized_effect"] / total < 0.95
    # Include the crossing parameter so the selected set reaches >=95%.
    crossing = ranking.index[ranking["cumulative_fraction"] >= 0.95]
    if len(crossing):
        ranking.loc[: int(crossing[0]), "selected_top95"] = True
    selected = set(ranking.loc[ranking.selected_top95, "parameter"])
    bounds = pd.read_csv(args.bounds, encoding="utf-8-sig")
    bounds["status"] = bounds.apply(
        lambda row: "active" if str(row["name"]).strip().upper() in selected else ("fixed" if str(row["status"]).lower() != "disabled" else "disabled"),
        axis=1,
    )
    fixed = bounds["status"].eq("fixed")
    bounds.loc[fixed, "lower"] = bounds.loc[fixed, "init"]
    bounds.loc[fixed, "upper"] = bounds.loc[fixed, "init"]
    args.out_ranking.parent.mkdir(parents=True, exist_ok=True)
    args.out_bounds.parent.mkdir(parents=True, exist_ok=True)
    ranking.to_csv(args.out_ranking, index=False)
    bounds.to_csv(args.out_bounds, index=False)
    print(f"cases={len(mio)} parameters={len(ranking)} selected_top95={len(selected)}")
    print(",".join(sorted(selected)))

if __name__ == "__main__":
    main()
