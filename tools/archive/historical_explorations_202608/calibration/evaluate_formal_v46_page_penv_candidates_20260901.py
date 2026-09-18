"""Deterministic three-candidate audit for the v46 PAGE/PENV formal run."""
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
RUN = ROOT / "workspace/runs/e02_formal_v46_page_penv_n034_20260901_r3"
CASE = "e02_formal_v46_page_penv_n034_20260901_r3"
DESIGN = ROOT / "configs/runs/e02_formal_v46_page_penv_n034_20260901.json"
OUT = ROOT / "workspace/reports/e02_formal_v46_page_penv_n034_20260901_candidates"
sys.path.insert(0, str(ROOT / "tools/analysis"))
from render_arm_d_best17_diagnostics_20260820 import (  # noqa: E402
    build_season_harvest_compare,
    build_season_process_compare,
    compute_metrics,
)


def _candidate_parameters() -> dict[str, pd.DataFrame]:
    phi = pd.read_csv(RUN / f"{CASE}.phi.actual.csv")
    final = phi.iloc[-1]
    real_cols = [c for c in phi.columns if c.isdigit()]
    vals = pd.to_numeric(final[real_cols], errors="coerce").dropna()
    best = str(vals.idxmin())
    top_n = max(1, int(math.ceil(len(vals) * 0.10)))
    top = vals.nsmallest(top_n).index.astype(str)

    obs = pd.read_csv(RUN / f"{CASE}.4.obs.csv")
    registry = pd.read_csv(RUN / f"{CASE}_observation_registry.csv")
    active = registry.loc[
        registry["phi_role"].astype(str).str.lower().eq("calibration")
        & (pd.to_numeric(registry["weight"], errors="coerce") > 0)
    ].copy()
    den = float(np.sum((pd.to_numeric(active["raw_obsval"], errors="coerce") - pd.to_numeric(active["raw_obsval"], errors="coerce").mean()) ** 2))
    nse_by_member: dict[str, float] = {}
    for member in obs["real_name"].astype(str):
        pred = []
        for _, row in active.iterrows():
            value = float(obs.loc[obs["real_name"].astype(str).eq(member), str(row["obsnme"]).lower()].iloc[0])
            if str(row.get("transform", "raw")).lower() == "log":
                value = math.exp(value) * float(row.get("transform_reference", 1.0)) - float(row.get("transform_offset", 0.0))
            pred.append(value)
        err = np.asarray(pred) - pd.to_numeric(active["raw_obsval"], errors="coerce").to_numpy(float)
        nse_by_member[member] = float(1.0 - np.sum(err * err) / den) if den > 0 else float("nan")
    top_nse = max(top, key=lambda x: nse_by_member.get(str(x), -np.inf))

    par = pd.read_csv(RUN / f"{CASE}.4.par.csv")
    par["real_name"] = par["real_name"].astype(str)
    by_name = {"lowest_phi": best, "top10_phi_highest_nse": str(top_nse)}
    outputs: dict[str, pd.DataFrame] = {}
    for label, name in by_name.items():
        row = par.loc[par["real_name"].eq(name)].iloc[0]
        outputs[label] = pd.DataFrame({"name": [c for c in par.columns if c != "real_name"], "value": [row[c] for c in par.columns if c != "real_name"]})
    median = par.drop(columns=["real_name"]).apply(pd.to_numeric, errors="coerce").median()
    outputs["posterior_median"] = pd.DataFrame({"name": median.index, "value": median.values})
    return outputs


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


def _response_metrics(run_dir: Path, registry: pd.DataFrame, token: str, output_name: str, value_token: str) -> list[dict[str, object]]:
    """Pair merged response output with registry rows in instruction order."""
    path = run_dir / output_name
    if not path.is_file():
        return []
    values = [float(m.group(1)) for m in re.finditer(rf"@{value_token}@\s+([-+0-9.eE]+)", path.read_text(encoding="utf-8", errors="ignore"))]
    rows = registry.loc[registry["sim_token"].astype(str).eq(token)].copy().reset_index(drop=True)
    if len(values) != len(rows):
        return [{"season": "all", "variable": token, "n": len(values), "error": f"output/registry length mismatch {len(values)}/{len(rows)}"}]
    out = []
    frame = pd.DataFrame({"obs": pd.to_numeric(rows["raw_obsval"], errors="coerce"), "sim": values, "season": rows["season_id"].astype(str)})
    for season, g in frame.groupby("season"):
        m = compute_metrics(g.obs.to_numpy(float), g.sim.to_numpy(float))
        out.append({"season": season, "variable": token, "n": len(g), **m})
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    registry = pd.read_csv(RUN / f"{CASE}_observation_registry.csv")
    candidates = _candidate_parameters()
    summary: list[dict[str, object]] = []
    metrics: list[dict[str, object]] = []
    for label, params in candidates.items():
        dest = _run(label, params)
        for season in ("25SP", "26SP"):
            sdir = dest / "_seasons" / season
            for kind, variables, builder in (("harvest", ["FRESH_INC", "FRESH_CUM"], build_season_harvest_compare), ("process", ["LAID", "LWAD", "SWAD", "CHTD"], build_season_process_compare)):
                frame = builder(sdir, season)
                for variable in variables:
                    oc, sc = f"OBS_{variable}", f"SIM_{variable}"
                    if oc in frame and sc in frame:
                        metrics.append({"candidate": label, "season": season, "kind": kind, "variable": variable, "n": len(frame), **compute_metrics(frame[oc].to_numpy(float), frame[sc].to_numpy(float))})
        metrics.extend({"candidate": label, **r} for r in _response_metrics(dest, registry, "NRESPS", "PestNResponse.OUT", "NRESPS"))
        metrics.extend({"candidate": label, **r} for r in _response_metrics(dest, registry, "WRESPS", "PestWResponse.OUT", "WRESPS"))
        summary.append({"candidate": label, "run_dir": str(dest), "parameter_csv": str(OUT / f"{label}_params.csv")})
    pd.DataFrame(metrics).to_csv(OUT / "candidate_metrics.csv", index=False, encoding="utf-8-sig")
    payload = {"source_run": str(RUN), "final_phi": pd.read_csv(RUN / f"{CASE}.phi.actual.csv").iloc[-1][["mean", "standard_deviation", "min", "max"]].to_dict(), "candidates": summary, "metrics_csv": str(OUT / "candidate_metrics.csv")}
    (OUT / "candidate_selection_and_replay.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
