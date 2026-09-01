"""Select final-Phi members and render deterministic diagnostics for the 1.5x-N arms."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
REPORT = ROOT / "workspace/reports/e02_v46_1p5n_late_lwad_20260901"
EVAL_MOD = "tools.calibration.evaluate_fixedsoil_official_best189_20260813"


def select(run_dir: Path, label: str) -> tuple[int, str, float]:
    case = f"e02_formal_v46_1p5n_{label}_20260901"
    phi = pd.read_csv(run_dir / f"{case}.phi.actual.csv")
    final_iter = int(phi["iteration"].max())
    row = phi.loc[phi["iteration"].eq(final_iter)].iloc[0]
    members = [c for c in phi.columns if str(c).isdigit()]
    member = min(members, key=lambda c: float(phi.loc[phi["iteration"].eq(final_iter), c].iloc[0]))
    return final_iter, str(member), float(phi.loc[phi["iteration"].eq(final_iter), member].iloc[0])


def evaluate(run_dir: Path, label: str) -> dict[str, object]:
    case = f"e02_formal_v46_1p5n_{label}_20260901"
    it, member, phi = select(run_dir, label)
    mod = importlib.reload(importlib.import_module(EVAL_MOD))
    mod.RUN_DIR = run_dir
    mod.DET_ROOT = run_dir / f"best_member_{member}_deterministic_20260901"
    mod.OUT_ROOT = ROOT / f"figture/e02_formal_v46_1p5n_{label}_20260901"
    mod.FIGURE = ROOT / "figture"
    mod.CASE = case
    mod.BEST_MEMBER = member
    mod.SOURCE_ITERATION = it
    mod.BEST_PHI = phi
    mod.CALIBRATION_STATE = "completed_v46_1p5n_late_lwad"
    mod.ARTIFACT_TYPE = "formal_v46_1p5n_late_lwad_deterministic"
    mod.SPE = ROOT / "data/templates/genotype/TMGRO048.SPE.base"
    mod.OBS_REGISTRY = run_dir / f"{case}_observation_registry.csv"
    mod.PLOT_INCLUDE_ALL_TREATMENTS = True
    mod.MAPPING_CSV = ROOT / "configs/runs/e02_mapping_26sp_w2_w1_20260830.csv"
    mod.SEASONS = [
        {"season_id": "25SP", "excode": "XXQL2501", "treatments": [2,3,4,5,9,10,11,12,13,14], "bundle": ROOT / "data/user/experiments/xxql2501_scheme4_1p5n_20260901"},
        {"season_id": "26SP", "excode": "XXQL2601", "treatments": list(range(1,13)), "bundle": ROOT / "data/user/experiments/xxql2601_scheme4_1p5n_20260901"},
    ]
    mod.CALIBRATION_TREATMENTS = {"25SP": [2,5,10,13], "26SP": [2,3,11,12]}
    mod.DIAGNOSTIC_TREATMENTS = {"25SP": [3,4,9,11,12,14], "26SP": [1,4,5,6,7,8,9,10]}
    mod.main()
    metrics = mod.DET_ROOT / "metrics_by_season_variable.csv"
    return {"label": label, "run_dir": str(run_dir), "iteration": it, "member": member, "phi": phi, "metrics_csv": str(metrics)}


def main() -> None:
    runs = {
        "baseline": ROOT / "workspace/runs/e02_formal_v46_1p5n_baseline_100x3_20260901_r3",
        "late_lwad2x": ROOT / "workspace/runs/e02_formal_v46_1p5n_late_lwad2x_100x3_20260901_r3",
    }
    out = [evaluate(path, label) for label, path in runs.items()]
    (REPORT / "deterministic_summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
