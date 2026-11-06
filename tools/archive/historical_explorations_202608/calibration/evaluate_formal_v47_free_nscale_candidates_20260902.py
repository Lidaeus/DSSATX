"""Deterministic three-candidate audit for the v47 freer-condition formal run."""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "workspace/runs/e02_formal_v47_free_nscale_200x6_20260901_r2"
CASE = "e02_formal_v47_free_nscale_200x6_20260901"
DESIGN = ROOT / "configs/runs/e02_formal_v47_free_nscale_20260901.json"
OUT = ROOT / "workspace/reports/e02_formal_v47_free_nscale_20260902_candidates"
FINAL_ITERATION = 6
sys.path.insert(0, str(ROOT / "tools/analysis"))
from render_arm_d_best17_diagnostics_20260820 import (  # noqa: E402
    build_season_harvest_compare,
    build_season_process_compare,
    compute_metrics,
)


def _raw_simulation_row(obs: pd.DataFrame, member: str, active: pd.DataFrame) -> np.ndarray:
    source = obs.loc[obs["real_name"].astype(str).eq(member)].iloc[0]
    pred: list[float] = []
    for _, row in active.iterrows():
        value = float(source[str(row["obsnme"]).lower()])
        if str(row.get("transform", "raw")).lower() == "log":
            value = math.exp(value) * float(row.get("transform_reference", 1.0)) - float(row.get("transform_offset", 0.0))
        pred.append(value)
    return np.asarray(pred, dtype=float)


def _candidate_parameters() -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    phi = pd.read_csv(RUN / f"{CASE}.phi.actual.csv")
    final = phi.iloc[-1]
    real_cols = [c for c in phi.columns if c.isdigit()]
    vals = pd.to_numeric(final[real_cols], errors="coerce").dropna()
    best = str(vals.idxmin())
    top_n = max(1, int(math.ceil(len(vals) * 0.10)))
    top = vals.nsmallest(top_n).index.astype(str)

    obs = pd.read_csv(RUN / f"{CASE}.{FINAL_ITERATION}.obs.csv")
    registry = pd.read_csv(RUN / f"{CASE}_observation_registry.csv")
    active = registry.loc[
        registry["phi_role"].astype(str).str.lower().eq("calibration")
        & (pd.to_numeric(registry["weight"], errors="coerce") > 0)
    ].copy().reset_index(drop=True)

    # Rank only within the best 10% Phi.  Average season/family NSE values so
    # unrelated variables are never pooled into a shared SST denominator.
    scores: dict[str, float] = {}
    for member in top:
        pred = _raw_simulation_row(obs, str(member), active)
        family_scores: list[float] = []
        for (_, _), idx in active.groupby(["season_id", "sim_token"], dropna=False).groups.items():
            loc = np.asarray(list(idx), dtype=int)
            target = pd.to_numeric(active.loc[loc, "raw_obsval"], errors="coerce").to_numpy(float)
            valid = np.isfinite(target) & np.isfinite(pred[loc])
            if valid.sum() < 2:
                continue
            den = float(np.sum((target[valid] - target[valid].mean()) ** 2))
            if den > 0:
                family_scores.append(float(1.0 - np.sum((pred[loc][valid] - target[valid]) ** 2) / den))
        scores[str(member)] = float(np.mean(family_scores)) if family_scores else -np.inf
    top_science = max(top, key=lambda x: scores.get(str(x), -np.inf))

    par = pd.read_csv(RUN / f"{CASE}.{FINAL_ITERATION}.par.csv")
    par["real_name"] = par["real_name"].astype(str)
    identities = {"lowest_phi": best, "top10_phi_balanced_nse": str(top_science)}
    outputs: dict[str, pd.DataFrame] = {}
    for label, name in identities.items():
        row = par.loc[par["real_name"].eq(name)].iloc[0]
        outputs[label] = pd.DataFrame({"name": [c for c in par.columns if c != "real_name"], "value": [row[c] for c in par.columns if c != "real_name"]})
    median = par.drop(columns=["real_name"]).apply(pd.to_numeric, errors="coerce").median()
    outputs["posterior_median"] = pd.DataFrame({"name": median.index, "value": median.values})
    identities["posterior_median"] = "ensemble_median"
    return outputs, identities


def _run(label: str, params: pd.DataFrame) -> Path:
    dest = OUT / f"run_{label}"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    pfile = OUT / f"{label}_params.csv"
    params.to_csv(pfile, index=False)
    cmd = [sys.executable, "-X", "utf8", str(ROOT / "src/calibration/run_multiseason.py"), "--design", str(DESIGN), "--param-csv", str(pfile), "--harvest-var", "CHFPW", "--prefix", f"candidate_{label}", "--keep-nitrogen-outputs"]
    proc = subprocess.run(cmd, cwd=dest, capture_output=True, text=True, env={**dict(__import__("os").environ), "PYTHONPATH": str(ROOT)})
    (dest / "runner.stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (dest / "runner.stderr.txt").write_text(proc.stderr, encoding="utf-8")
    if proc.returncode:
        raise RuntimeError(f"{label} deterministic run failed: {proc.stderr[-2000:]}")
    return dest


def _response_metrics(run_dir: Path, registry: pd.DataFrame, token: str, output_name: str) -> list[dict[str, object]]:
    path = run_dir / output_name
    if not path.is_file():
        return []
    values = [float(m.group(1)) for m in re.finditer(rf"@{token}@\s+([-+0-9.eE]+)", path.read_text(encoding="utf-8", errors="ignore"))]
    rows = registry.loc[registry["sim_token"].astype(str).eq(token)].copy().reset_index(drop=True)
    if len(values) != len(rows):
        return [{"season": "all", "variable": token, "n": len(values), "error": f"output/registry length mismatch {len(values)}/{len(rows)}"}]
    frame = pd.DataFrame({"obs": pd.to_numeric(rows["raw_obsval"], errors="coerce"), "sim": values, "season": rows["season_id"].astype(str)})
    return [{"season": season, "variable": token, "n": len(g), **compute_metrics(g.obs.to_numpy(float), g.sim.to_numpy(float))} for season, g in frame.groupby("season")]


def _terminal_metrics(frame: pd.DataFrame) -> dict[str, float]:
    work = frame.copy()
    time_col = next((c for c in ("HDAY", "DATE", "DAP", "HARVEST") if c in work.columns), None)
    treatment_col = next((c for c in ("TRNO", "TN", "treatment") if c in work.columns), None)
    if time_col and treatment_col:
        work = work.sort_values(time_col).groupby(treatment_col, as_index=False).tail(1)
    return compute_metrics(work["OBS_FRESH_CUM"].to_numpy(float), work["SIM_FRESH_CUM"].to_numpy(float))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    registry = pd.read_csv(RUN / f"{CASE}_observation_registry.csv")
    candidates, identities = _candidate_parameters()
    metrics: list[dict[str, object]] = []
    summary: list[dict[str, object]] = []
    for label, params in candidates.items():
        dest = _run(label, params)
        for season in ("25SP", "26SP"):
            sdir = dest / "_seasons" / season
            harvest = build_season_harvest_compare(sdir, season)
            for variable in ("FRESH_INC", "FRESH_CUM"):
                oc, sc = f"OBS_{variable}", f"SIM_{variable}"
                if oc in harvest and sc in harvest:
                    metrics.append({"candidate": label, "season": season, "kind": "harvest", "variable": variable, "n": int((np.isfinite(harvest[oc]) & np.isfinite(harvest[sc])).sum()), **compute_metrics(harvest[oc].to_numpy(float), harvest[sc].to_numpy(float))})
            if "OBS_FRESH_CUM" in harvest and "SIM_FRESH_CUM" in harvest:
                metrics.append({"candidate": label, "season": season, "kind": "harvest_terminal", "variable": "FRESH_TERMINAL", **_terminal_metrics(harvest)})
            process = build_season_process_compare(sdir, season)
            for variable in ("LAID", "LWAD", "SWAD", "CHTD"):
                oc, sc = f"OBS_{variable}", f"SIM_{variable}"
                if oc in process and sc in process:
                    metrics.append({"candidate": label, "season": season, "kind": "process", "variable": variable, "n": int((np.isfinite(process[oc]) & np.isfinite(process[sc])).sum()), **compute_metrics(process[oc].to_numpy(float), process[sc].to_numpy(float))})
        metrics.extend({"candidate": label, "kind": "response", **r} for r in _response_metrics(dest, registry, "NRESPS", "PestNResponse.OUT"))
        metrics.extend({"candidate": label, "kind": "response", **r} for r in _response_metrics(dest, registry, "WRESPS", "PestWResponse.OUT"))
        summary.append({"candidate": label, "member": identities[label], "run_dir": str(dest), "parameter_csv": str(OUT / f"{label}_params.csv")})
    pd.DataFrame(metrics).to_csv(OUT / "candidate_metrics.csv", index=False, encoding="utf-8-sig")
    payload = {"source_run": str(RUN), "final_phi": pd.read_csv(RUN / f"{CASE}.phi.actual.csv").iloc[-1][["mean", "standard_deviation", "min", "max"]].to_dict(), "candidates": summary, "metrics_csv": str(OUT / "candidate_metrics.csv")}
    (OUT / "candidate_selection_and_replay.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
