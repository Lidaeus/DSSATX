"""Read existing calibration evidence; never run DSSAT or edit source artifacts.

Output defaults to a new directory and refuses to overwrite an existing one.
Independent numpy formulas deliberately cross-check the production metric code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RUNS = {
    "v48_55": "e02_formal_v48_n_gradient_water2x_200x4_20260902_r2",
    "fix_191": "e02_formal_v48_fix_xfpht_xfint_200x4_20260903_r1",
    "26only_39": "e02_formal_v48_26sp_only_200x4_20260903_r1",
    "del_pending": "e02_formal_v48_del_xfpht_xfint_200x4_20260903_r1",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=False)
    sources, metrics, gradients, summaries, params, families = {}, [], [], [], [], []

    def track(path):
        path = Path(path)
        sources[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return path

    def read(path):
        return pd.read_csv(track(path))

    mapping = read(ROOT / "configs/runs/e02_mapping_26sp_w2_w1_20260830.csv")

    def score(label, season, variable, obs, sim, signed=False):
        o, s = np.asarray(obs, float), np.asarray(sim, float)
        valid = np.isfinite(o) & np.isfinite(s)
        if not signed:
            valid &= (o >= 0) & (s >= 0)
        o, s = o[valid], s[valid]
        if not len(o):
            return
        e = s - o
        sst = np.sum((o - o.mean()) ** 2)
        metrics.append(dict(candidate=label, season=season, variable=variable, n=len(o),
                            rmse=np.sqrt(np.mean(e**2)), bias=e.mean(),
                            rrmse_pct=100*np.sqrt(np.mean(e**2))/abs(o.mean()) if o.mean() else np.nan,
                            nse=1-np.sum(e**2)/sst if sst else np.nan))

    def harvest_scores(label, season, frame):
        for variable in ("FRESH_CUM", "FRESH_INC", "DRY_CUM", "DRY_INC"):
            if f"OBS_{variable}" in frame:
                score(label, season, variable, frame[f"OBS_{variable}"], frame[f"SIM_{variable}"])
        terminal = frame.sort_values("HNO").groupby("TN").tail(1)
        score(label, season, "FRESH_TERMINAL", terminal.OBS_FRESH_CUM, terminal.SIM_FRESH_CUM)
        joined = terminal.merge(mapping[mapping.season_id.eq(season)], left_on="TN", right_on="treatment", validate="one_to_one")
        for water, group in joined.groupby("water_level"):
            g = group.set_index("nitrogen_level")
            if not {"N1", "N2", "N3"} <= set(g.index):
                continue
            o = g.loc[["N1", "N2", "N3"], "OBS_FRESH_CUM"].to_numpy()
            s = g.loc[["N1", "N2", "N3"], "SIM_FRESH_CUM"].to_numpy()
            gradients.append(dict(candidate=label, season=season, water=water,
                                  obs_N3_N1=o[2]-o[0], sim_N3_N1=s[2]-s[0],
                                  adjacent_rmse=np.sqrt(np.mean((np.diff(s)-np.diff(o))**2)),
                                  obs_cv_pct=100*np.std(o)/np.mean(o), sim_cv_pct=100*np.std(s)/np.mean(s)))

    registries = {}
    for label, dirname in RUNS.items():
        directory = ROOT / "workspace/runs" / dirname
        status = json.loads(track(directory / "run_status.json").read_text(encoding="utf-8"))
        summary = dict(candidate=label, run_dir=str(directory.relative_to(ROOT)), **{k: status.get(k) for k in ("status", "engineering_status", "scientific_status", "started_at", "finished_at")})
        summaries.append(summary)
        # Running files are not treated as completed evidence.
        if status["status"] != "completed":
            continue
        phi_path = next(directory.glob("*.phi.actual.csv"))
        case = phi_path.name.removesuffix(".phi.actual.csv")
        phi = read(phi_path)
        row = phi.iloc[-1]
        columns = [c for c in phi if str(c).isdigit() or c == "base"]
        member = row[columns].astype(float).idxmin()
        iteration = int(row.iteration)
        registry = read(directory / f"{case}_observation_registry.csv")
        registry["key"] = registry.obsnme.str.lower()
        registry = registry.set_index("key")
        registries[label] = registry
        observations = read(directory / f"{case}.{iteration}.obs.csv").set_index("real_name")
        observations.index = observations.index.astype(str)
        sim = observations.loc[member].reindex(registry.index).astype(float)
        assert np.isfinite(sim).all(), f"missing ensemble outputs: {label}"
        weighted = ((sim-registry.obsval)*registry.weight)**2
        calculated_phi = float(weighted.sum())
        assert abs(calculated_phi-float(row[member])) < 0.1, (label, calculated_phi, row[member])
        par = read(directory / f"{case}.{iteration}.par.csv").set_index("real_name")
        par.index = par.index.astype(str)
        params.extend(dict(candidate=label, parameter=k, value=float(v)) for k,v in par.loc[member].items())
        summary.update(iteration=iteration, member=member, actual_mean=float(row["mean"]),
                       actual_min=float(row[member]), phi_recomputed=calculated_phi,
                       ensemble_size=len(observations), n_observations=len(registry),
                       n_positive_weight=int((registry.weight > 0).sum()))
        f = registry.copy()
        f["phi"] = weighted
        f["family"] = f.sim_token.str.replace(r"^SW\d+S$", "SOIL_WATER", regex=True)
        for (season, family), part in f.groupby(["season_id", "family"]):
            families.append(dict(candidate=label, season=season, family=family, phi=part.phi.sum(), n_active=int((part.weight>0).sum())))
        raw_sim = sim.copy()
        log = registry["transform"].eq("log")
        raw_sim.loc[log] = np.exp(sim.loc[log])*registry.loc[log,"transform_reference"]-registry.loc[log,"transform_offset"]
        registry = registry.assign(raw_sim=raw_sim)
        for season, part in registry.groupby("season_id"):
            for token in ("LAIDS", "LWADS", "SWADS", "CHTDS", "NRESPS", "WRESPS"):
                g = part[part.sim_token.eq(token)]
                score(label, season, token, g.raw_obsval, g.raw_sim, signed=token in {"NRESPS", "WRESPS"})
            cumulative = part[part.sim_token.isin(["CHFPWS", "CHFPWS_T"])].copy()
            cumulative["HNO"] = cumulative.obsnme.str.extract(r"_H(\d+)$", expand=False).astype(int)
            h = cumulative.rename(columns={"treatment":"TN", "raw_obsval":"OBS_FRESH_CUM", "raw_sim":"SIM_FRESH_CUM"})
            harvest_scores(label, season, h)
            g = part[part.sim_token.eq("HFPOWS")]
            score(label, season, "FRESH_INC", g.raw_obsval, g.raw_sim)

    # Establish that fixing the two parameters did not change observation targets/weights.
    same_contract = registries["v48_55"][["obsval","weight","sim_token","transform"]].equals(registries["fix_191"][["obsval","weight","sim_token","transform"]])
    assert same_contract
    v52 = ROOT / "workspace/reports/v52_photo_senescence_20260902"
    candidates = {"C01":"fine_p025_canopyE_last0.17", "C02":"p025_canopyE", "C03":"p0_canopyE", "C04":"p0_control"}
    candidates["26only_cross_replay"] = "unused"
    for label, dirname in candidates.items():
        directory = (ROOT / "workspace/runs" / RUNS["26only_39"] / "best_member_39_two_season_deterministic_20260903") if label == "26only_cross_replay" else v52 / dirname
        for season in ("25SP", "26SP"):
            p = directory / "_seasons" / season
            h = read(p / f"{season}_deterministic_harvest_compare.csv")
            assert not h.duplicated(["TN","HNO"]).any()
            harvest_scores(label, season, h)
            g = read(p / f"{season}_deterministic_process_compare.csv")
            for variable in ("LAID","LWAD","SWAD","CHTD"):
                score(label, season, variable+"S", g[f"OBS_{variable}"], g[f"SIM_{variable}"])
    for name, records in [("run_snapshot",summaries), ("raw_metrics",metrics), ("terminal_n_gradient",gradients), ("selected_parameters",params), ("phi_families",families)]:
        pd.DataFrame(records).to_csv(args.out_dir / f"{name}.csv",index=False,encoding="utf-8-sig")
    manifest = dict(created_at_utc=datetime.now(timezone.utc).isoformat(),
                    git_commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
                    scope="read-only audit of persisted artifacts; no model execution; not science finalization",
                    fixed_vs_free_same_observation_contract=same_contract, sources_sha256=sources)
    (args.out_dir / "audit_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print(pd.DataFrame(summaries).to_string(index=False))
    print(pd.DataFrame(metrics).query("variable in ['FRESH_CUM','FRESH_TERMINAL','FRESH_INC','LAIDS']").round(4).to_string(index=False))


if __name__ == "__main__":
    main()
