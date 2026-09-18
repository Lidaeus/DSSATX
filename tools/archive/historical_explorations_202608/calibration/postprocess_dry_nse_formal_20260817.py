"""Select and deterministically replay three candidates from the formal run."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.calibration.finalize_calibration import verify_calibration_artifact_manifest
from src.calibration.stage_representative import resolve_final_iteration

CASE = "e02_fixedsoil_nse_official_25sp26sp_200x6_20260817"
RUN_DIR = ROOT / "workspace/runs" / CASE
OUT_ROOT = ROOT / "figture/formal_confirmation_20260817"


def _nse(observed: np.ndarray, simulated: np.ndarray) -> float:
    valid = np.isfinite(observed) & np.isfinite(simulated)
    obs, sim = observed[valid], simulated[valid]
    sst = float(np.square(obs - obs.mean()).sum())
    return 1.0 - float(np.square(sim - obs).sum()) / sst


def _real_col(frame: pd.DataFrame) -> str:
    for col in frame.columns:
        if str(col).lower() in {"real_name", "realization"}:
            return str(col)
    return str(frame.columns[0])


def _normal_real(value: object) -> str:
    return str(value).removesuffix(".0")


def _export_member(frame: pd.DataFrame, real: str, path: Path) -> None:
    key = _real_col(frame)
    rows = frame[frame[key].map(_normal_real).eq(real)]
    if len(rows) != 1:
        raise ValueError(f"realization {real!r} occurs {len(rows)} times")
    row = rows.iloc[0]
    records = [{"name": str(c).upper(), "value": float(row[c])} for c in frame.columns if c != key and math.isfinite(float(row[c]))]
    pd.DataFrame(records).to_csv(path, index=False)


def _candidate_table(iteration: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    obs = pd.read_csv(RUN_DIR / f"{CASE}.{iteration}.obs.csv", index_col=0)
    obs.index = obs.index.map(_normal_real)
    obs.columns = obs.columns.astype(str).str.lower()
    phi = pd.read_csv(RUN_DIR / f"{CASE}.phi.actual.csv")
    phi_row = phi.loc[pd.to_numeric(phi["iteration"]).eq(iteration)].iloc[0]
    registry = pd.read_csv(RUN_DIR / f"{CASE}_observation_registry.csv", encoding="utf-8-sig")
    dry = registry[registry["sim_token"].astype(str).isin(["CHPDTS_T", "CHPDTS"])].copy()
    names = dry["obsnme"].astype(str).str.lower().tolist()
    observed = pd.to_numeric(dry["raw_obsval"], errors="raise").to_numpy(float)
    season = dry["season_id"].astype(str).to_numpy()
    reserved = {"iteration", "total_runs", "mean", "standard_deviation", "min", "max"}
    phi_by_real = {_normal_real(c): float(phi_row[c]) for c in phi.columns if c not in reserved}
    rows = []
    for real in obs.index:
        simulated = pd.to_numeric(obs.loc[real, names], errors="raise").to_numpy(float)
        item = {"realization": real, "total_phi": phi_by_real[real], "dry_nse_pooled": _nse(observed, simulated)}
        for sid in ("25SP", "26SP"):
            mask = season == sid
            item[f"dry_nse_{sid.lower()}"] = _nse(observed[mask], simulated[mask])
        rows.append(item)
    return pd.DataFrame(rows), pd.read_csv(RUN_DIR / f"{CASE}.{iteration}.par.csv")


def _run_deterministic(label: str, params: Path, iteration: int, member: str | None, phi: float | None) -> None:
    import tools.calibration.evaluate_fixedsoil_official_best189_20260813 as evaluation

    def export_selected(out_csv: Path) -> int:
        selected = pd.read_csv(params)
        selected.to_csv(out_csv, index=False)
        return len(selected)

    evaluation.CASE = CASE
    evaluation.RUN_DIR = RUN_DIR
    evaluation.SOURCE_ITERATION = iteration
    evaluation.BEST_MEMBER = label
    evaluation.BEST_PHI = float(phi) if phi is not None else math.nan
    evaluation.CALIBRATION_STATE = "engineering_validated"
    evaluation.ARTIFACT_TYPE = "formal_confirmation_deterministic_candidate"
    evaluation.OBS_REGISTRY = RUN_DIR / f"{CASE}_observation_registry.csv"
    evaluation.OUT_ROOT = OUT_ROOT / label
    evaluation.DET_ROOT = RUN_DIR / "deterministic_candidates" / label
    evaluation.EXTRA_LIMITATIONS = [
        "Candidate was selected from the final iteration under the formal dry-NSE contract.",
        "Raw cumulative dry weights satisfy phi_season = 75*(1-NSE_season).",
    ]
    evaluation._export_member = export_selected
    rc = evaluation.main()
    if rc:
        raise RuntimeError(f"deterministic replay failed for {label}: exit {rc}")
    manifest_path = evaluation.OUT_ROOT / "diagnostic_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update({
        "selection_rule": label, "source_realization": member,
        "selected_calibration_phi": phi, "objective_identity": "phi_season = 75*(1-NSE_season)",
        "source_parameter_csv": str(params.resolve()),
    })
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    verify_calibration_artifact_manifest(RUN_DIR, CASE)
    iteration, _ = resolve_final_iteration(RUN_DIR, CASE)
    if iteration != 6:
        raise RuntimeError(f"Expected final iteration 6, got {iteration}")
    members, par = _candidate_table(iteration)
    minimum = members.sort_values(["total_phi", "realization"]).iloc[0]
    cutoff = float(members["total_phi"].quantile(0.10))
    compromise = members[members["total_phi"] <= cutoff].sort_values(
        ["dry_nse_pooled", "total_phi", "realization"], ascending=[False, True, True]
    ).iloc[0]

    candidate_dir = RUN_DIR / "calibration_finalize/deterministic_candidates"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    selections = [
        ("minimum_phi", minimum),
        ("phi_q10_highest_nse", compromise),
    ]
    audit_rows = []
    for label, row in selections:
        real = str(row["realization"])
        path = candidate_dir / f"{label}_params.csv"
        _export_member(par, real, path)
        audit_rows.append({"selection_rule": label, **row.to_dict(), "parameter_csv": str(path)})

    median_source = RUN_DIR / "calibration_finalize/stage_representative_params.csv"
    median_path = candidate_dir / "ensemble_median_params.csv"
    median = pd.read_csv(median_source)
    median.to_csv(median_path, index=False)
    audit_rows.append({
        "selection_rule": "ensemble_median", "realization": None, "total_phi": None,
        "dry_nse_pooled": None, "dry_nse_25sp": None, "dry_nse_26sp": None,
        "parameter_csv": str(median_path),
    })
    audit = pd.DataFrame(audit_rows)
    audit.to_csv(candidate_dir / "candidate_selection_audit.csv", index=False)
    payload = {
        "schema_version": 1, "case": CASE, "final_iteration": iteration,
        "phi_q10_cutoff": cutoff, "selection_table": audit_rows,
        "note": "Median candidate has no ensemble-member Phi/NSE; its metrics are produced by deterministic replay.",
    }
    (candidate_dir / "candidate_selection_audit.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for row in audit_rows:
        _run_deterministic(
            str(row["selection_rule"]), Path(str(row["parameter_csv"])), iteration,
            None if pd.isna(row["realization"]) else str(row["realization"]),
            None if pd.isna(row["total_phi"]) else float(row["total_phi"]),
        )
    payload["status"] = "completed"
    payload["diagnostic_root"] = str(OUT_ROOT.resolve())
    (candidate_dir / "deterministic_candidate_manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(audit.to_string(index=False))
    print(f"diagnostics={OUT_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
