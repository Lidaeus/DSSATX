"""Run the controlled 1.5x initial-N v46 calibration comparison.

Arm A: 1.5x SNH4/SNO3, v46 weights.
Arm B: same inputs, but 2x weight on the final two 26SP LWAD increments.
Both arms use 100 realizations, noptmax=3 and six agents to keep attribution
clear and computational cost bounded.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "workspace/reports/e02_v46_1p5n_late_lwad_20260901"
SETUP = ROOT / "tools/calibration/setup_v46_1p5n_late_lwad_20260901.py"
PORTS = {"baseline": 4231, "late_lwad2x": 4232}


def build_and_run(label: str, design_rel: str) -> Path:
    case = f"e02_formal_v46_1p5n_{label}_20260901"
    run_id = f"e02_formal_v46_1p5n_{label}_100x3_20260901_r3"
    run_dir = ROOT / "workspace/runs" / run_id
    if run_dir.exists() and any(run_dir.iterdir()):
        raise FileExistsError(f"refusing to mix existing run directory: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    design = ROOT / design_rel
    policy = REPORT / "e02_v46_1p5n_late_lwad2x_observation_policy.csv" if label == "late_lwad2x" else ROOT / "configs/runs/e02_from_scratch_objective_contract_20260826.csv"
    build = [sys.executable, str(ROOT / "src/calibration/build_pest.py"),
             "--mode", "eggplant_stage2", "--prefix", case,
             "--bounds-id", "eggplant_e02_v37_formal_source_sink_balanced_bounds",
             "--bounds-crop", "eggplant", "--multiseason-design", str(design),
             "--observation-policy-csv", str(policy), "--noptmax", "3",
             "--ies-num-reals", "100", "--batch", "DSSBatch.v48",
             "--harvest-var", "CHFPW", "--param-review-mode", "off",
             "--out-dir", str(run_dir)]
    (REPORT / f"{label}_build.log").parent.mkdir(parents=True, exist_ok=True)
    with (REPORT / f"{label}_build.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(build, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"{label}: build failed ({result.returncode})")
    reg = pd.read_csv(run_dir / f"{case}_observation_registry.csv", encoding="utf-8-sig")
    positive = reg[pd.to_numeric(reg["weight"], errors="coerce") > 0]
    expected = {"25SP": {2, 5, 10, 13}, "26SP": {2, 3, 11, 12}}
    for season, cells in expected.items():
        actual = set(pd.to_numeric(positive.loc[positive.season_id.eq(season), "treatment"], errors="coerce").dropna().astype(int))
        if actual != cells:
            raise RuntimeError(f"{label}: active treatment scope {season}={sorted(actual)}")
    if label == "late_lwad2x":
        late = reg[reg["obgnme"].isin(["26SP_LWADDM_D26180", "26SP_LWADDM_D26198"])]
        if late.empty or not (pd.to_numeric(late["sigma"], errors="coerce") == 10.0).all():
            raise RuntimeError(f"{label}: late LWAD multiplier audit failed")
    cmd = [sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
           "--run-dir", str(run_dir), "--case", case, "--mode", "ies",
           "--n-agents", "6", "--port", str(PORTS[label]), "--wait"]
    with (REPORT / f"{label}_run.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"{label}: parallel run failed ({result.returncode})")
    return run_dir


def summarize(run_dir: Path, label: str) -> dict[str, object]:
    case = f"e02_formal_v46_1p5n_{label}_20260901"
    phi = pd.read_csv(run_dir / f"{case}.phi.actual.csv")
    final = phi[phi["iteration"] == phi["iteration"].max()]
    numeric = [c for c in final.columns if str(c).isdigit()]
    best = final[numeric].astype(float).min().idxmin()
    return {"label": label, "run_dir": str(run_dir), "final_iteration": int(final["iteration"].max()), "best_member_by_final_phi": str(best), "best_final_phi": float(final[best].min()), "n_final_members": len(final)}


def main() -> int:
    subprocess.run([sys.executable, str(SETUP)], cwd=ROOT, check=True)
    manifest = json.loads((REPORT / "arm_manifest.json").read_text(encoding="utf-8"))
    out = []
    for item in manifest:
        label = item["label"]
        run_dir = build_and_run(label, item["design"])
        out.append(summarize(run_dir, label))
    (REPORT / "run_summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
