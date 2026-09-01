"""Deterministic screen of nitrogen-demand and mining triggers.

All non-screened parameters are frozen to v46 best71 member 71 and all 22
spring treatments are replayed.  This is deliberately a trigger test: it
records whether nitrogen stress becomes non-zero before the first harvest,
not just whether a terminal Phi-like score changes.
"""
from __future__ import annotations

import json
import hashlib
import re
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import tools.calibration.profile_n_parameters_determinstic as runner
import tools.calibration.profile_v46_best71_nitrogen_20260831 as metrics

ANCHOR = ROOT / "workspace/runs/e02_formal_v46_step20_custom26sp_20260831_200x4/best_member_71_deterministic_20260831"
OUT = ROOT / "workspace/reports/e02_v46_best71_nitrogen_demand_profile_20260831"
SCRATCH = OUT / "scratch_runs"


def _stress_at_first_harvest(path: Path) -> dict[str, float]:
    """Read PlantGro stress columns at 26SP DOY 146 (HNO1 date)."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    header = next((x for x in lines if x.startswith("@YEAR")), None)
    if not header:
        return {"n_rows": 0}
    cols = header[1:].split()
    rows = []
    for line in lines:
        fields = line.split()
        if fields and fields[0] == "2026" and len(fields) == len(cols) and fields[1] == "146":
            rows.append(fields)
    if not rows:
        return {"n_rows": 0}
    frame = pd.DataFrame(rows, columns=cols)
    out: dict[str, float] = {"n_rows": float(len(frame))}
    for name in ("NSTD", "PST1A", "PST2A"):
        vals = pd.to_numeric(frame[name], errors="coerce")
        out[f"{name}_h1_max"] = float(vals.max())
        out[f"{name}_h1_mean"] = float(vals.mean())
        out[f"{name}_h1_nonzero_n"] = float((vals.abs() > 1e-9).sum())
    return out


def _run(changes: dict[str, float], case: str) -> dict[str, object]:
    result_file = SCRATCH / case / "profile_result.json"
    if result_file.is_file():
        return json.loads(result_file.read_text(encoding="utf-8"))
    result = runner._run_deterministic(changes, case)
    if not result:
        return {"case": case, "status": "failed"}
    result.update(metrics._terminal_n12(case))
    stress = _stress_at_first_harvest(SCRATCH / case / "_seasons/26SP/PlantGro.OUT")
    result.update(stress)
    result_file.parent.mkdir(parents=True, exist_ok=True)
    result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    runner.BASE_PARAMS_PATH = ANCHOR / "best_member_71_params.csv"
    runner.OUT_DIR = OUT
    runner.SCRATCH_DIR = SCRATCH
    runner.BASE_DESIGN_PATH = OUT / "design_demand_profile.json"
    metrics.SCRATCH = SCRATCH

    design = json.loads((ROOT / "configs/runs/e02_formal_v46_step20_custom26sp_20260831_200x4.json").read_text(encoding="utf-8"))
    for season in design["seasons"]:
        season["treatments"] = {"25SP": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
                                "26SP": list(range(1, 13))}[season["season_id"]]
    design["design_id"] = "e02_v46_best71_nitrogen_demand_profile_20260831"
    design["purpose"] = "Deterministic PROLFI/NMOBMX trigger profile"
    design["diagnostic_only"] = {"25SP": [], "26SP": []}
    runner.BASE_DESIGN_PATH.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    experiments: list[tuple[str, str, dict[str, float]]] = [("baseline", "BASELINE", {})]
    for v in [0.12, 0.20871, 0.30, 0.40, 0.60]:
        experiments.append((f"prolfi_{v:.5f}", "PROLFI", {"PROLFI": v}))
    for v in [0.10, 0.25, 0.398148, 0.60, 0.85]:
        experiments.append((f"nmobmx_{v:.6f}", "NMOBMX", {"NMOBMX": v}))
    for prolfi, nmobmx in product([0.12, 0.20871, 0.40], [0.10, 0.398148, 0.85]):
        experiments.append((f"prolfi_{prolfi:.5f}_nmobmx_{nmobmx:.6f}", "PROLFI_NMOBMX",
                            {"PROLFI": prolfi, "NMOBMX": nmobmx}))

    rows = []
    for i, (case, family, changes) in enumerate(experiments, 1):
        row = _run(changes, case)
        row.update({"case": case, "family": family, "setting": "|".join(f"{k}={v}" for k, v in changes.items()) or "best71"})
        rows.append(row)
        pd.DataFrame(rows).to_csv(OUT / "demand_profile_results.csv", index=False, encoding="utf-8-sig")
        print(f"[{i:02d}/{len(experiments):02d}] {case}", flush=True)

    df = pd.DataFrame(rows)
    if not df.empty:
        base = df.iloc[0]
        if "n12_mean_abs_error" in df:
            df["n_response_error_delta_vs_baseline"] = df["n12_mean_abs_error"] - float(base["n12_mean_abs_error"])
        df["trigger_activated_h1"] = (
            pd.to_numeric(df.get("NSTD_h1_max", 0), errors="coerce").fillna(0).gt(1e-9)
            | pd.to_numeric(df.get("PST1A_h1_max", 0), errors="coerce").fillna(0).gt(1e-9)
            | pd.to_numeric(df.get("PST2A_h1_max", 0), errors="coerce").fillna(0).gt(1e-9)
        )
        df.to_csv(OUT / "demand_profile_scorecard.csv", index=False, encoding="utf-8-sig")
        def sha256(path: Path) -> str:
            h = hashlib.sha256()
            with path.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    h.update(chunk)
            return h.hexdigest()
        manifest = {
            "schema_version": 1,
            "profile": "e02_v46_best71_nitrogen_demand_profile_20260831",
            "anchor_params": str((ANCHOR / "best_member_71_params.csv").resolve()),
            "anchor_params_sha256": sha256(ANCHOR / "best_member_71_params.csv"),
            "design": str(runner.BASE_DESIGN_PATH.resolve()),
            "design_sha256": sha256(runner.BASE_DESIGN_PATH),
            "seasons": {"25SP": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14], "26SP": list(range(1, 13))},
            "case_count": int(len(df)),
            "screened_parameters": ["PROLFI", "NMOBMX"],
            "diagnostic_fields": ["NSTD", "PST1A", "PST2A"],
            "source_note": "TMT observations and PestHarvest/FreshWt replay; N0 retained in structural audit",
        }
        (OUT / "demand_profile_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
