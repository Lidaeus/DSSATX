"""Conditional-ensemble replay exporter for the uncertainty figure pipeline.

Reads the final PEST-IES parameter ensemble (``*.N.par.csv``), deterministically
re-runs DSSAT for every retained ensemble member over the two spring seasons'
full treatment sets (25SP: 10 treatments, 26SP: 12 treatments; 25FA is
hard-excluded), and freezes the renderer-neutral conditional prediction tables
consumed by ``paper/R/fig_model_performance_uncertainty.R``,
``fig_treatment_residual_uncertainty.R`` and the conditional dynamics modules.

Terminology (frozen in ``docs/conditional_ensemble_P0_audit_20260828.md``):
the PEST-IES final parameter ensemble is the *conditional parameter ensemble*;
deterministic per-member replays yield the *95% conditional-ensemble
prediction interval* (``interval_semantics = parameter_conditional_ensemble_only``).
Never "confidence interval" / "credible interval".

This module never imports a plotting library: Python owns replay, validation,
aggregation and freezing; R remains the only paper-figure renderer.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.common.quality import (  # noqa: E402
    QualityReport,
    ScientificQualityError,
    load_quality_report,
    read_flat_run_manifest_field,
)
from src.reporting.analyze_results import (  # noqa: E402
    _nearest_on_or_before,
    _read_freshwt_var_by_run,
    _read_plantgro_vars_by_run,
    _read_tmt_harvest_obs,
    _read_tmt_process_obs,
    _yyddd_add_days,
)
from src.reporting.figure_data import VARIABLE_SPECS, read_dssat_trajectories  # noqa: E402

# ── frozen data contracts (plan §7) ─────────────────────────────────────────
# variable_label/unit are appended after the plan-§7 columns so the frozen
# schema keeps the plan's column list as a strict prefix; R reads them for
# axis labels exactly like comparison.csv.
PREDICTION_SUMMARY_COLUMNS = [
    "run_id", "ensemble_iteration", "season_id", "dataset_role", "treatment", "variable",
    "time", "date_code", "dap", "harvest_number", "observed", "observed_se",
    "sim_mean", "sim_median", "sim_q025", "sim_q25", "sim_q75", "sim_q975",
    "n_members_expected", "n_members_valid", "source_file",
    "variable_label", "unit",
]
TRAJECTORY_SUMMARY_COLUMNS = [
    "run_id", "ensemble_iteration", "season_id", "dataset_role", "treatment", "variable",
    "date_code", "dap", "sim_mean", "sim_median", "sim_q025", "sim_q25", "sim_q75",
    "sim_q975", "n_members_expected", "n_members_valid", "source_file",
    "variable_label", "unit",
]
RESIDUAL_MEMBER_COLUMNS = [
    "run_id", "realization", "season_id", "dataset_role", "treatment", "variable",
    "n_events", "signed_relative_bias_pct", "rrmse_pct", "terminal_relative_error_pct",
    "member_phi", "member_status",
]

ALLOWED_SEASON_IDS = ("25SP", "26SP")
EVENT_VARIABLES = ("DRY_INC", "DRY_CUM", "FRESH_INC", "FRESH_CUM", "LAID", "LWAD", "SWAD", "CWAD")
TRAJECTORY_VARIABLES = ("LAID", "LWAD", "SWAD", "CWAD", "DRY_CUM", "FRESH_CUM")
CUMULATIVE_VARIABLES = ("DRY_CUM", "FRESH_CUM")
PROCESS_SOURCE_VARIABLES = ("LAID", "LWAD", "SWAD", "CWAD")
QUANTILES = (0.025, 0.25, 0.5, 0.75, 0.975)
QUANTILE_COLUMNS = ("sim_q025", "sim_q25", "sim_median", "sim_q75", "sim_q975")

# FileA/FileT missing-value sentinel family; anything at or below never enters
# quantiles or metrics (plan §10 gate 8).
SENTINEL_THRESHOLD = -90.0
GLOBAL_MEMBER_RATE_GATE = 0.98
# Environment overrides that would silently change bundle/soil resolution and
# break the "same environment as calibration" rule are cleared per worker.
CLEARED_ENV_OVERRIDES = (
    "DSSAT_SOIL_BASE", "DSSAT_BATCH_FILEX_ROOT", "DSSAT_FILEX_BASE", "DSSAT_FILEX_MAP",
)
_WATER_LEVELS = ("W1", "W2", "W3", "CK")
_NITROGEN_LEVELS = ("N0", "N1", "N2", "N3")
# observation_uncertainty.csv variable → frozen contract variable
_UNCERTAINTY_VARIABLE_MAP = {
    "LAID": "LAID", "LWAD": "LWAD", "SWAD": "SWAD",
    "CHPDT": "DRY_CUM", "CHFPW": "FRESH_CUM", "HPODW": "DRY_INC",
}


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path) -> dict[str, str]:
    return {"path": path.name, "sha256": _sha256(path)}


def _write_csv(frame: pd.DataFrame, path: Path) -> Path:
    frame.to_csv(path, index=False, encoding="utf-8")
    return path


# ── input loading and validation ────────────────────────────────────────────

def load_parameter_ensemble(par_csv: Path) -> pd.DataFrame:
    """Load the final PEST++ parameter ensemble, excluding the base member.

    The ``base`` row is not a random conditional-ensemble member and must never
    enter the interval (plan §3.1).
    """
    frame = pd.read_csv(par_csv)
    if "real_name" not in frame.columns:
        raise ValueError(f"parameter ensemble lacks real_name column: {par_csv}")
    if frame["real_name"].duplicated().any():
        raise ValueError("parameter ensemble has duplicate real_name values")
    frame = frame[frame["real_name"].astype(str) != "base"].copy()
    if frame.empty:
        raise ValueError("parameter ensemble has no non-base members")
    parameter_columns = [c for c in frame.columns if c != "real_name"]
    numeric = frame[parameter_columns].apply(pd.to_numeric, errors="coerce")
    bad_rows = (~np.isfinite(numeric)).any(axis=1)
    if bad_rows.any():
        names = frame.loc[bad_rows, "real_name"].tolist()
        raise ValueError(f"non-finite parameter values in members: {names}")
    frame[parameter_columns] = numeric
    frame["member_order"] = pd.to_numeric(frame["real_name"], errors="coerce")
    if frame["member_order"].isna().any():
        raise ValueError("non-numeric realization names beside 'base' are not supported")
    return frame.sort_values("member_order").drop(columns="member_order").reset_index(drop=True)


def load_member_status(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"real_name", "state", "final_status"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"member status file missing columns: {sorted(missing)}")
    return frame


def load_member_phi(phi_csv: Path, iteration: int) -> dict[str, float]:
    """Realization-level Phi of the final iteration (never the reported mean)."""
    frame = pd.read_csv(phi_csv)
    if "iteration" not in frame.columns:
        raise ValueError(f"phi history lacks iteration column: {phi_csv}")
    rows = frame[frame["iteration"] == iteration]
    if rows.empty:
        raise ValueError(f"phi history has no iteration {iteration}: {phi_csv}")
    row = rows.iloc[-1]
    result: dict[str, float] = {}
    for column in frame.columns:
        if column == "iteration":
            continue
        try:
            value = float(row[column])
        except (TypeError, ValueError):
            continue
        if np.isfinite(value) and value >= 0 and column != "total_runs":
            try:
                key = str(int(float(column)))
            except ValueError:
                continue
            result[key] = value
    return result


def build_tpl_name_mapping(tpl_path: Path) -> dict[str, str]:
    """Map lowercase PEST ensemble column names back to template (DSSAT) casing."""
    mapping: dict[str, str] = {}
    for raw in tpl_path.read_text(encoding="utf-8", errors="strict").splitlines():
        line = raw.strip()
        if not line or line.startswith("ptf") or line.startswith("name,value"):
            continue
        name = line.split(",", 1)[0].strip()
        if name and name != "name":
            mapping[name.lower()] = name
    if not mapping:
        raise ValueError(f"no parameter names found in template: {tpl_path}")
    return mapping


def load_two_season_metadata(path: Path) -> pd.DataFrame:
    """Load and validate the frozen season-aware water-nitrogen metadata."""
    frame = pd.read_csv(path, dtype={"treatment": str})
    required = ["season_id", "treatment", "treatment_label", "water_level", "nitrogen_level", "dataset_role"]
    missing = [c for c in required if c not in frame.columns]
    if missing:
        raise ValueError(f"two-season treatment metadata missing columns: {missing}")
    seasons = sorted(set(frame["season_id"]))
    if set(seasons) != set(ALLOWED_SEASON_IDS):
        raise ValueError(
            f"two-season metadata must cover exactly {ALLOWED_SEASON_IDS}, got {seasons}"
        )
    if frame.duplicated(["season_id", "treatment"]).any():
        raise ValueError("two-season treatment metadata has duplicate season x treatment rows")
    unknown_water = set(frame["water_level"]) - set(_WATER_LEVELS)
    unknown_nitrogen = set(frame["nitrogen_level"]) - set(_NITROGEN_LEVELS)
    if unknown_water or unknown_nitrogen:
        raise ValueError(
            f"unknown water/nitrogen levels: water={sorted(unknown_water)} "
            f"nitrogen={sorted(unknown_nitrogen)}"
        )
    unknown_role = set(frame["dataset_role"]) - {"calibration", "validation"}
    if unknown_role:
        raise ValueError(f"unknown dataset roles in frozen metadata: {sorted(unknown_role)}")
    expected = {"25SP": 10, "26SP": 12}
    for season, count in expected.items():
        actual = int((frame["season_id"] == season).sum())
        if actual != count:
            raise ValueError(f"{season} must list {count} treatments, found {actual}")
    return frame


def load_observed_se(bundle_by_season: dict[str, Path]) -> pd.DataFrame:
    """Audited replicate SE per (season, treatment, date, contract variable)."""
    rows = []
    for season, bundle in bundle_by_season.items():
        path = bundle / "observation_uncertainty.csv"
        if not path.is_file():
            continue
        frame = pd.read_csv(path)
        for source, variable in _UNCERTAINTY_VARIABLE_MAP.items():
            part = frame[
                (frame["variable"].astype(str).str.upper() == source)
                & (pd.to_numeric(frame["raw_sd"], errors="coerce") > 0)
            ].copy()
            if part.empty:
                continue
            sd = pd.to_numeric(part["raw_sd"], errors="coerce")
            n_rep = pd.to_numeric(part["n_rep"], errors="coerce").clip(lower=1)
            part = part.assign(
                season_id=season,
                treatment=part["trno"].astype(str),
                date_code=pd.to_numeric(part["date"], errors="coerce").astype("Int64"),
                observed_se=(sd / np.sqrt(n_rep)).astype(float),
                contract_variable=variable,
            )
            rows.append(part[["season_id", "treatment", "date_code", "contract_variable", "observed_se"]])
    if not rows:
        return pd.DataFrame(columns=["season_id", "treatment", "date_code", "contract_variable", "observed_se"])
    return pd.concat(rows, ignore_index=True)


# ── replay environment freezing ─────────────────────────────────────────────

@dataclass
class ReplayEnvironment:
    """Verified, hash-recorded replay environment (plan §3.2)."""

    dssat_exe: Path
    dssat_exe_sha256: str
    genotype_templates: dict[str, str]
    season_bundles: dict[str, dict[str, str]]
    calibration_design: Path
    calibration_design_sha256: str
    cleared_env: tuple[str, ...] = CLEARED_ENV_OVERRIDES

    def as_dict(self) -> dict[str, Any]:
        return {
            "dssat_exe": str(self.dssat_exe),
            "dssat_exe_sha256": self.dssat_exe_sha256,
            "genotype_templates": dict(self.genotype_templates),
            "season_bundles": {k: dict(v) for k, v in self.season_bundles.items()},
            "calibration_design": str(self.calibration_design),
            "calibration_design_sha256": self.calibration_design_sha256,
            "cleared_env_overrides": list(self.cleared_env),
        }


def _same_path(left: Path, right: str) -> bool:
    if not right:
        return False
    candidate = Path(right)
    if not candidate.is_absolute():
        candidate = _PROJECT_ROOT / candidate
    return left.resolve() == candidate.resolve()


def _replay_sandbox_root(out_dir: Path, replay_root_base: Path) -> Path:
    """Short-path member sandbox root.

    DSSAT's batch FileX field is only 93 characters wide; deep output trees
    such as ``paper_data/conditional_predictions/_replay/member_0`` exceed it
    even after Windows 8.3 shortening.  Members therefore run under a short
    ``<replay_root_base>/<token>`` tree (token derived from the out dir) and
    only the frozen CSVs live in the deep output directory.
    """
    import hashlib

    token = hashlib.sha1(str(out_dir.resolve()).encode("utf-8")).hexdigest()[:8]
    return replay_root_base / token


def verify_replay_environment(
    *,
    run_dir: Path,
    official_dssat: Path,
    calibration_design: Path,
    season_bundles: dict[str, Path],
    case: str,
) -> ReplayEnvironment:
    """Freeze and verify every replay input against the calibration run."""
    official_dssat = official_dssat.resolve()
    if not official_dssat.is_file():
        raise ValueError(f"official DSSAT executable not found: {official_dssat}")
    exe_sha = _sha256(official_dssat)
    # Cross-check against the run's formal launch receipt when present.
    receipt_path = run_dir / "formal_launch_receipt.json"
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        expected = str(receipt.get("official_exe_sha256", "")).lower()
        if expected and expected != exe_sha:
            raise ValueError(
                "official DSSAT exe hash does not match formal_launch_receipt.json "
                f"({exe_sha} != {expected}); replay environment is not the calibrated one"
            )

    design_data = json.loads(calibration_design.read_text(encoding="utf-8"))
    design_seasons = {s["season_id"]: s for s in design_data.get("seasons", [])}

    templates: dict[str, str] = {}
    gen_dir = _PROJECT_ROOT / "data" / "templates" / "genotype"
    for stem in ("TMGRO048.CUL", "TMGRO048.ECO", "TMGRO048.SPE"):
        template = gen_dir / f"{stem}.base"
        if not template.is_file():
            raise ValueError(f"genotype template missing: {template}")
        templates[stem + ".base"] = _sha256(template)

    bundle_records: dict[str, dict[str, str]] = {}
    for season, bundle in season_bundles.items():
        if season not in ALLOWED_SEASON_IDS:
            raise ValueError(
                f"season {season!r} is not part of the two-spring replay set {ALLOWED_SEASON_IDS}; "
                "25FA must not enter this bundle"
            )
        manifest = bundle / "input_manifest.json"
        if not manifest.is_file():
            raise ValueError(f"season bundle has no input_manifest.json: {bundle}")
        actual = _sha256(manifest)
        declared = str(design_seasons.get(season, {}).get("bundle_manifest_sha256", "")).lower()
        if not declared:
            raise ValueError(f"calibration design does not declare a manifest hash for {season}")
        if actual != declared:
            raise ValueError(
                f"{season} bundle manifest {actual} does not match the calibrated design "
                f"hash {declared}; replay must use the exact calibration bundles"
            )
        bundle_records[season] = {
            "path": str(bundle),
            "manifest_sha256": actual,
            "bundle_path_matches_design": _same_path(
                bundle, str(design_seasons[season].get("bundle_path", ""))
            ),
        }

    if not season_bundles.get("25SP") or not season_bundles.get("26SP"):
        raise ValueError("both 25SP and 26SP bundles are required (repeatable --season)")

    return ReplayEnvironment(
        dssat_exe=official_dssat,
        dssat_exe_sha256=exe_sha,
        genotype_templates=templates,
        season_bundles=bundle_records,
        calibration_design=calibration_design.resolve(),
        calibration_design_sha256=_sha256(calibration_design),
    )


def build_replay_design(
    *,
    calibration_design: Path,
    metadata: pd.DataFrame,
    season_bundles: dict[str, Path],
    case: str,
    out_path: Path,
) -> Path:
    """Compose the replay design covering every treatment of both seasons."""
    source = json.loads(calibration_design.read_text(encoding="utf-8"))
    design_seasons = {s["season_id"]: s for s in source.get("seasons", [])}
    seasons = []
    for season in ALLOWED_SEASON_IDS:
        treatments = (
            metadata.loc[metadata["season_id"] == season, "treatment"]
            .astype(int).sort_values().tolist()
        )
        code = design_seasons.get(season, {}).get("experiment_code")
        if not code:
            raise ValueError(f"calibration design lacks experiment_code for {season}")
        bundle = season_bundles[season]
        seasons.append(
            {
                "season_id": season,
                "experiment_code": str(code),
                "bundle_path": str(bundle),
                "bundle_manifest_sha256": _sha256(bundle / "input_manifest.json"),
                # run_multiseason executes calibration-role seasons; this replay
                # is a deterministic evaluation and never constructs Phi.
                "role": "calibration",
                "treatments": treatments,
            }
        )
    payload = {
        "schema_version": 1,
        "design_id": f"conditional_replay_{case}_{datetime.now(timezone.utc):%Y%m%d}",
        "cultivar_identity": source.get("cultivar_identity", "TM0008"),
        "shared_parameter_scope": source.get("shared_parameter_scope", ""),
        "bounds_id": source.get("bounds_id", ""),
        "observation_policy": source.get("observation_policy", ""),
        "group_policy": source.get("group_policy", ""),
        "purpose": "conditional-ensemble deterministic replay over all two-spring treatments",
        "harvest_dry_objective": {"enabled": False},
        "process_state_objective": {"enabled": False},
        "nitrogen_response_objective": {"enabled": False},
        "water_response_objective": {"enabled": False},
        "seasons": seasons,
    }
    if not payload["observation_policy"] or not payload["group_policy"]:
        raise ValueError("calibration design lacks observation_policy/group_policy")
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out_path


# ── per-member replay and extraction ────────────────────────────────────────

_RUN_TN_PATTERN = re.compile(r"\*RUN\s+(\d+).*?XXQL\d+\s+(\d+)", re.IGNORECASE)


def _run_to_treatment_map(plantgro_path: Path) -> dict[int, int]:
    mapping: dict[int, int] = {}
    for line in plantgro_path.read_text(errors="ignore").splitlines():
        if line.startswith("*RUN"):
            match = _RUN_TN_PATTERN.search(line)
            if match:
                mapping[int(match.group(1))] = int(match.group(2))
    return mapping


def _matched_date_on_or_before(series: dict[int, float], target: int) -> int | None:
    dates = [d for d in series if d <= target]
    return max(dates) if dates else None


def extract_member_events(
    *,
    season_dir: Path,
    season_id: str,
    experiment_code: str,
    roles: dict[str, str],
    dap_lookup: dict[tuple[str, int], float],
) -> pd.DataFrame:
    """Event-level observed/simulated pairs using the frozen matching rules.

    Harvest events match FileT dates to FreshWt.OUT CHPDT/CHFPW with the same
    d+1 bounded on-or-before window as the deterministic compare builder;
    process events match FileT dates to PlantGro.OUT on-or-before.  Sentinel
    observations (<= -90) never enter the table.
    """
    tmt_path = season_dir / f"{experiment_code}.TMT"
    plantgro = season_dir / "PlantGro.OUT"
    freshwt = season_dir / "FreshWt.OUT"
    run_to_tn = _run_to_treatment_map(plantgro)
    obs_harvest = _read_tmt_harvest_obs(str(tmt_path))
    obs_process = _read_tmt_process_obs(str(tmt_path), list(PROCESS_SOURCE_VARIABLES))
    sim_dry = _read_freshwt_var_by_run(str(freshwt), "CHPDT")
    sim_fresh = _read_freshwt_var_by_run(str(freshwt), "CHFPW")
    sim_process = _read_plantgro_vars_by_run(str(plantgro), list(PROCESS_SOURCE_VARIABLES))

    rows: list[dict[str, Any]] = []
    for run_no, tn in sorted(run_to_tn.items()):
        role = roles.get(str(tn), "validation")
        # Harvest events (cumulative via bounded nearest, increment as
        # consecutive cumulative difference — identical to the deterministic
        # compare builder).
        prev_dry: float | None = None
        prev_fresh: float | None = None
        for event in obs_harvest.get(tn, []):
            date = int(event["DATE"])
            sim_date = _yyddd_add_days(date, 1)
            values: dict[str, tuple[float | None, int | None]] = {}
            for prefix, series in (("DRY", sim_dry), ("FRESH", sim_fresh)):
                member_series = series.get(run_no, {})
                cum = _nearest_on_or_before(member_series, sim_date)
                matched = _matched_date_on_or_before(member_series, sim_date)
                if cum is None or matched is None:
                    cum_value = None
                    inc_value = None
                else:
                    cum_value = float(cum)
                    prev = prev_dry if prefix == "DRY" else prev_fresh
                    inc_value = cum_value if prev is None else cum_value - prev
                values[f"{prefix}_CUM"] = (cum_value, matched)
                values[f"{prefix}_INC"] = (inc_value, matched)
                if prefix == "DRY":
                    prev_dry = cum_value
                else:
                    prev_fresh = cum_value
            for variable in ("DRY_INC", "DRY_CUM", "FRESH_INC", "FRESH_CUM"):
                observed = float(event.get(f"OBS_{variable}", -99.0))
                if observed <= SENTINEL_THRESHOLD:
                    continue
                simulated, matched = values[variable]
                if simulated is None or matched is None:
                    continue
                dap = dap_lookup.get((str(tn), matched))
                if dap is None:
                    continue
                rows.append(
                    {
                        "season_id": season_id,
                        "dataset_role": role,
                        "treatment": str(tn),
                        "variable": variable,
                        "harvest_number": int(event["HNO"]),
                        "date_code": date,
                        "dap": float(dap),
                        "observed": observed,
                        "simulated": simulated,
                        "source_file": f"{experiment_code}.TMT+FreshWt.OUT",
                    }
                )
        # Process events (on-or-before daily match on PlantGro.OUT).
        series_by_date = sim_process.get(run_no, {})
        for point in obs_process.get(tn, []):
            date = int(point["DATE"])
            matched = date if date in series_by_date else _matched_date_on_or_before(series_by_date, date)
            if matched is None:
                continue
            day = series_by_date[matched]
            for variable in PROCESS_SOURCE_VARIABLES:
                observed = float(point.get(f"OBS_{variable}", -99.0))
                if observed <= SENTINEL_THRESHOLD:
                    continue
                simulated = day.get(variable)
                if simulated is None or not np.isfinite(float(simulated)) or float(simulated) <= SENTINEL_THRESHOLD:
                    continue
                dap = dap_lookup.get((str(tn), matched))
                if dap is None:
                    continue
                rows.append(
                    {
                        "season_id": season_id,
                        "dataset_role": role,
                        "treatment": str(tn),
                        "variable": variable,
                        "harvest_number": None,
                        "date_code": date,
                        "dap": float(dap),
                        "observed": observed,
                        "simulated": float(simulated),
                        "source_file": f"{experiment_code}.TMT+PlantGro.OUT",
                    }
                )
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError(f"no event pairs extracted from {season_dir}")
    return frame


def extract_member_trajectory(
    *,
    season_dir: Path,
    season_id: str,
    run_id: str,
    data_status: str,
    roles: dict[str, str],
) -> pd.DataFrame:
    """Daily DSSAT trajectories (PlantGro + FreshWt) slimmed to replay columns."""
    frame = read_dssat_trajectories(
        season_dir, run_id=run_id, data_status=data_status, role_by_treatment=roles
    )
    keep = frame[["variable", "treatment", "date_code", "time", "simulated"]].copy()
    keep = keep.rename(columns={"time": "dap"})
    keep.insert(0, "season_id", season_id)
    return keep


@dataclass
class MemberJob:
    real_name: str
    member_dir: Path
    param_records: list[tuple[str, float]]
    design_path: Path
    season_specs: list[dict[str, Any]]  # [{season_id, experiment_code, roles}]
    dssat_exe_dir: str
    keep_outputs: bool = False
    run_id: str = "conditional_replay"
    data_status: str = "legacy_unvalidated"


def _replay_member(job_dict: dict[str, Any]) -> dict[str, Any]:
    """Worker task: one isolated member replay + immediate extraction."""
    job = MemberJob(**job_dict)
    member_dir = Path(job.member_dir)
    member_dir.mkdir(parents=True, exist_ok=True)
    param_csv = member_dir / "member_params.csv"
    lines = ["name,value"] + [f"{name},{value!r}" for name, value in job.param_records]
    param_csv.write_text("\n".join(lines) + "\n", encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(_PROJECT_ROOT)
    for key in CLEARED_ENV_OVERRIDES:
        env.pop(key, None)
    # Guarantee the calibrated executable resolves first inside run_dssat.
    env["PATH"] = job.dssat_exe_dir + os.pathsep + env.get("PATH", "")

    command = [
        sys.executable,
        str(_PROJECT_ROOT / "src" / "calibration" / "run_multiseason.py"),
        # The subprocess cwd is the isolated member sandbox, so every path
        # argument must be absolute or it would resolve against the sandbox.
        "--design", str(Path(job.design_path).resolve()),
        "--param-csv", str(param_csv.resolve()),
        "--prefix", f"replay_r{job.real_name}",
        "--harvest-var", "CHPDT",
        "--model", "CRGRO048",
    ]
    started = time.monotonic()
    completed = subprocess.run(
        command, cwd=str(member_dir), env=env, capture_output=True, text=True
    )
    elapsed = time.monotonic() - started
    (member_dir / "replay.stdout.log").write_text(completed.stdout, encoding="utf-8", errors="replace")
    (member_dir / "replay.stderr.log").write_text(completed.stderr, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        if not job.keep_outputs:
            _safe_rmtree(member_dir)
        return {
            "real_name": job.real_name,
            "status": "failed",
            "reason": f"run_multiseason exit {completed.returncode}; see replay.stderr.log",
            "elapsed_s": elapsed,
            "events": None,
            "trajectory": None,
        }

    try:
        event_frames = []
        trajectory_frames = []
        for spec in job.season_specs:
            season_dir = member_dir / "_seasons" / spec["season_id"]
            trajectory = extract_member_trajectory(
                season_dir=season_dir,
                season_id=spec["season_id"],
                run_id=job.run_id,
                data_status=job.data_status,
                roles=spec["roles"],
            )
            dap_lookup = {
                (str(row.treatment), int(row.date_code)): float(row.dap)
                for row in trajectory.drop_duplicates(["treatment", "date_code"]).itertuples(index=False)
            }
            events = extract_member_events(
                season_dir=season_dir,
                season_id=spec["season_id"],
                experiment_code=spec["experiment_code"],
                roles=spec["roles"],
                dap_lookup=dap_lookup,
            )
            trajectory_frames.append(trajectory)
            event_frames.append(events)
        events = pd.concat(event_frames, ignore_index=True)
        trajectory = pd.concat(trajectory_frames, ignore_index=True)
    except Exception as exc:  # noqa: BLE001 — record any extraction failure
        if not job.keep_outputs:
            _safe_rmtree(member_dir)
        return {
            "real_name": job.real_name,
            "status": "failed",
            "reason": f"extraction error: {type(exc).__name__}: {exc}",
            "elapsed_s": elapsed,
            "events": None,
            "trajectory": None,
        }

    if not job.keep_outputs:
        # Raw DSSAT outputs are disposable after extraction (plan §8.1 item 5).
        for season_spec in job.season_specs:
            _safe_rmtree(member_dir / "_seasons" / season_spec["season_id"])
    return {
        "real_name": job.real_name,
        "status": "ok",
        "reason": "",
        "elapsed_s": elapsed,
        "events": events,
        "trajectory": trajectory,
    }


def _safe_rmtree(path: Path) -> None:
    """Windows-tolerant removal: retry past transient indexer/AV dir locks."""
    for attempt in range(6):
        try:
            shutil.rmtree(path, ignore_errors=False)
            return
        except PermissionError:
            if attempt == 5:
                # Last resort: best-effort rename so a later run starts clean.
                try:
                    shutil.rmtree(path, ignore_errors=True)
                except OSError:
                    pass
            time.sleep(0.2 * (attempt + 1))


# ── aggregation and freezing ────────────────────────────────────────────────

@dataclass
class ReplayAggregate:
    prediction_summary: pd.DataFrame
    trajectory_summary: pd.DataFrame
    residual_members: pd.DataFrame
    member_availability: pd.DataFrame
    valid_members: list[str]
    dropped_incomplete_points: dict[str, int]
    observed_consistent: bool


def _quantile_columns(values: np.ndarray) -> dict[str, float]:
    qs = np.quantile(values, QUANTILES, method="linear")
    return dict(zip(QUANTILE_COLUMNS, (float(q) for q in qs)))


def _check_quantile_order(frame: pd.DataFrame) -> None:
    ordered = (
        (frame["sim_q025"] <= frame["sim_q25"])
        & (frame["sim_q25"] <= frame["sim_median"])
        & (frame["sim_median"] <= frame["sim_q75"])
        & (frame["sim_q75"] <= frame["sim_q975"])
    )
    if not bool(ordered.all()):
        raise ValueError("quantile ordering q025<=q25<=median<=q75<=q975 violated")


def _check_cumulative_monotone(summary: pd.DataFrame, *, time_column: str, label: str) -> None:
    for variable in CUMULATIVE_VARIABLES:
        part = summary[summary["variable"] == variable]
        if part.empty:
            continue
        for _, group in part.groupby(["season_id", "treatment"]):
            group = group.sort_values(time_column)
            for column in ("sim_mean",) + QUANTILE_COLUMNS:
                values = group[column].to_numpy(float)
                tolerance = max(1e-9, float(np.nanmax(np.abs(values))) * 1e-9)
                if np.any(np.diff(values) < -tolerance):
                    raise ValueError(
                        f"{label} cumulative {variable} quantile curve decreases along "
                        f"{time_column}; refusing to freeze (season {group['season_id'].iloc[0]}, "
                        f"treatment {group['treatment'].iloc[0]}, column {column})"
                    )


def _complete_case_members(
    events: pd.DataFrame,
    trajectory: pd.DataFrame,
    metadata: pd.DataFrame,
    candidates: list[str],
) -> tuple[list[str], dict[str, Any]]:
    """Members with every expected season x treatment covered in both tables."""
    expected_pairs = {(row.season_id, str(row.treatment)) for row in metadata.itertuples(index=False)}
    valid: list[str] = []
    demoted: list[dict[str, str]] = []
    for real in candidates:
        member_events = events[events["realization"] == real]
        member_traj = trajectory[trajectory["realization"] == real]
        event_pairs = set(zip(member_events["season_id"], member_events["treatment"].astype(str)))
        traj_pairs = set(zip(member_traj["season_id"], member_traj["treatment"].astype(str)))
        missing_events = expected_pairs - event_pairs
        missing_traj = expected_pairs - traj_pairs
        if missing_events or missing_traj:
            demoted.append(
                {
                    "realization": real,
                    "reason": (
                        f"missing trajectory pairs {sorted(missing_traj)}; "
                        f"missing event pairs {sorted(missing_events)}"
                    ),
                }
            )
        else:
            valid.append(real)
    return valid, {"demoted": demoted}


def _apply_uniform_points(
    frame: pd.DataFrame, key_columns: list[str], valid_members: list[str]
) -> tuple[pd.DataFrame, int]:
    """Restrict to (key, member) cells covered by every valid member."""
    # dropna=False keeps process-event rows whose harvest_number is None.
    coverage = frame.groupby(key_columns, observed=True, dropna=False)["realization"].nunique()
    expected = len(valid_members)
    complete_keys = coverage[coverage == expected]
    dropped = int(len(coverage) - len(complete_keys))
    if dropped == 0:
        return frame.copy(), 0
    key_index = pd.MultiIndex.from_frame(frame[key_columns])
    complete_index = complete_keys.index
    mask = key_index.isin(complete_index)
    return frame[mask].copy(), dropped


def aggregate_replay(
    *,
    events: pd.DataFrame,
    trajectory: pd.DataFrame,
    metadata: pd.DataFrame,
    candidate_members: list[str],
    run_id: str,
    ensemble_iteration: int,
    member_phi: dict[str, float],
    member_status: pd.DataFrame,
    observed_se_table: pd.DataFrame,
) -> ReplayAggregate:
    """Aggregate member replays into the three frozen contracts."""
    valid_members, demotion_info = _complete_case_members(events, trajectory, metadata, candidate_members)
    if not valid_members:
        raise ValueError(f"no complete-case members remain; detail: {demotion_info}")
    events = events[events["realization"].isin(valid_members)].copy()
    trajectory = trajectory[trajectory["realization"].isin(valid_members)].copy()

    event_key = ["season_id", "treatment", "variable", "date_code", "harvest_number"]
    events, dropped_event_points = _apply_uniform_points(events, event_key, valid_members)
    traj_key = ["season_id", "treatment", "variable", "dap"]
    trajectory, dropped_traj_points = _apply_uniform_points(trajectory, traj_key, valid_members)

    # Observed values come from the immutable bundle and must be identical
    # across members; any drift means the replay is not the calibrated input.
    obs_unique = events.groupby(event_key, dropna=False)["observed"].nunique()
    dap_unique = events.groupby(event_key, dropna=False)["dap"].nunique()
    observed_consistent = bool((obs_unique <= 1).all() and (dap_unique <= 1).all())
    if not observed_consistent:
        raise ValueError("observed values or matched DAP differ across members; replay inputs are inconsistent")

    n_expected = len(valid_members)
    grouped = events.groupby(event_key, sort=True, dropna=False)
    records = []
    for key, group in grouped:
        first = group.iloc[0]
        quantiles = _quantile_columns(group["simulated"].to_numpy(float))
        se_row = observed_se_table[
            (observed_se_table["season_id"] == key[0])
            & (observed_se_table["treatment"] == key[1])
            & (observed_se_table["date_code"] == int(key[3]))
            & (observed_se_table["contract_variable"] == key[2])
        ]
        observed_se = float(se_row["observed_se"].iloc[0]) if len(se_row) else np.nan
        records.append(
            {
                "run_id": run_id,
                "ensemble_iteration": int(ensemble_iteration),
                "season_id": key[0],
                "dataset_role": first["dataset_role"],
                "treatment": key[1],
                "variable": key[2],
                "time": float(first["dap"]),
                "date_code": int(key[3]),
                "dap": float(first["dap"]),
                "harvest_number": key[4],
                "observed": float(first["observed"]),
                "observed_se": observed_se,
                "sim_mean": float(group["simulated"].mean()),
                **quantiles,
                "n_members_expected": n_expected,
                "n_members_valid": int(len(group)),
                "source_file": first["source_file"],
                "variable_label": VARIABLE_SPECS[key[2]]["label"],
                "unit": VARIABLE_SPECS[key[2]]["unit"],
            }
        )
    prediction_summary = pd.DataFrame(records, columns=PREDICTION_SUMMARY_COLUMNS)
    prediction_summary = prediction_summary.sort_values(
        ["season_id", "treatment", "variable", "dap"], kind="stable"
    ).reset_index(drop=True)

    traj_records = []
    for key, group in trajectory.groupby(traj_key, sort=True):
        first = group.iloc[0]
        quantiles = _quantile_columns(group["simulated"].to_numpy(float))
        traj_records.append(
            {
                "run_id": run_id,
                "ensemble_iteration": int(ensemble_iteration),
                "season_id": key[0],
                "dataset_role": metadata_role(metadata, key[0], key[1]),
                "treatment": key[1],
                "variable": key[2],
                "date_code": int(first["date_code"]),
                "dap": float(key[3]),
                "sim_mean": float(group["simulated"].mean()),
                **quantiles,
                "n_members_expected": n_expected,
                "n_members_valid": int(len(group)),
                "source_file": "PlantGro.OUT/FreshWt.OUT",
                "variable_label": VARIABLE_SPECS[key[2]]["label"],
                "unit": VARIABLE_SPECS[key[2]]["unit"],
            }
        )
    trajectory_summary = pd.DataFrame(traj_records, columns=TRAJECTORY_SUMMARY_COLUMNS)
    trajectory_summary = trajectory_summary.sort_values(
        ["season_id", "treatment", "variable", "dap"], kind="stable"
    ).reset_index(drop=True)

    # Member-level treatment residuals (plan §5.2 formulas).
    residual_records = []
    status_lookup = {
        str(row.real_name): f"{row.state}/{row.final_status}"
        for row in member_status.itertuples(index=False)
    }
    events_sorted = events.sort_values(["realization", "season_id", "treatment", "variable", "dap"])
    for (real, season, treatment, variable), group in events_sorted.groupby(
        ["realization", "season_id", "treatment", "variable"], sort=True
    ):
        observed = group["observed"].to_numpy(float)
        simulated = group["simulated"].to_numpy(float)
        obs_sum = float(observed.sum())
        mean_abs_obs = float(np.mean(np.abs(observed)))
        signed_bias = 100.0 * float((simulated - observed).sum()) / obs_sum if obs_sum != 0 else np.nan
        rrmse = (
            100.0 * float(np.sqrt(np.mean((simulated - observed) ** 2))) / mean_abs_obs
            if mean_abs_obs > 0
            else np.nan
        )
        terminal_error = (
            100.0 * (float(simulated[-1]) - float(observed[-1])) / float(observed[-1])
            if observed[-1] != 0
            else np.nan
        )
        residual_records.append(
            {
                "run_id": run_id,
                "realization": real,
                "season_id": season,
                "dataset_role": group["dataset_role"].iloc[0],
                "treatment": treatment,
                "variable": variable,
                "n_events": int(len(group)),
                "signed_relative_bias_pct": signed_bias,
                "rrmse_pct": rrmse,
                "terminal_relative_error_pct": terminal_error,
                "member_phi": member_phi.get(str(real), np.nan),
                "member_status": status_lookup.get(str(real), "unknown"),
            }
        )
    residual_members = pd.DataFrame(residual_records, columns=RESIDUAL_MEMBER_COLUMNS)
    residual_members = residual_members.sort_values(
        ["season_id", "treatment", "variable", "realization"], kind="stable"
    ).reset_index(drop=True)

    availability = (
        events.groupby(["season_id", "treatment", "variable"])["realization"].nunique().reset_index(name="n_members_valid")
    )
    availability.insert(len(availability.columns), "n_members_expected", n_expected)

    _check_quantile_order(prediction_summary)
    _check_quantile_order(trajectory_summary)
    _check_cumulative_monotone(prediction_summary, time_column="dap", label="event")
    _check_cumulative_monotone(trajectory_summary, time_column="dap", label="daily")

    return ReplayAggregate(
        prediction_summary=prediction_summary,
        trajectory_summary=trajectory_summary,
        residual_members=residual_members,
        member_availability=availability,
        valid_members=valid_members,
        dropped_incomplete_points={
            "event_points": dropped_event_points,
            "trajectory_points": dropped_traj_points,
            **demotion_info,
        },
        observed_consistent=observed_consistent,
    )


def metadata_role(metadata: pd.DataFrame, season_id: str, treatment: str) -> str:
    rows = metadata[(metadata["season_id"] == season_id) & (metadata["treatment"].astype(str) == str(treatment))]
    if rows.empty:
        raise ValueError(f"treatment {treatment} of {season_id} is not in the frozen two-season metadata")
    return str(rows["dataset_role"].iloc[0])


def compute_interval_sensitivity(
    *,
    events: pd.DataFrame,
    valid_members: list[str],
    machine_flagged: set[str],
) -> pd.DataFrame:
    """Compare 95% interval endpoints with and without machine-flagged members.

    The pre-registered main set keeps every valid member regardless of Phi; the
    sensitivity subset drops members the machine quality report explicitly
    flagged.  Only endpoint differences are reported — the figure choice is
    never made by looking better.
    """
    if not machine_flagged:
        rows = []
        for variable in sorted(events["variable"].unique()):
            rows.append(
                {
                    "variable": variable,
                    "n_members_main": len(valid_members),
                    "n_members_sensitivity": len(valid_members),
                    "excluded_members": 0,
                    "max_abs_q025_diff": 0.0,
                    "max_abs_q975_diff": 0.0,
                    "mean_abs_q025_diff": 0.0,
                    "mean_abs_q975_diff": 0.0,
                }
            )
        return pd.DataFrame(rows)
    keep = [m for m in valid_members if m not in machine_flagged]
    if not keep:
        raise ValueError("interval sensitivity subset is empty")
    rows = []
    main_events = events[events["realization"].isin(valid_members)]
    subset_events = events[events["realization"].isin(keep)]
    key = ["season_id", "treatment", "variable", "date_code", "harvest_number"]
    for variable in sorted(events["variable"].unique()):
        diffs_025, diffs_975 = [], []
        grouped_main = main_events[main_events["variable"] == variable].groupby(key, dropna=False)["simulated"]
        grouped_subset = subset_events[subset_events["variable"] == variable].groupby(key, dropna=False)["simulated"]
        for group_key, values in grouped_main:
            if group_key not in grouped_subset.groups:
                continue
            main_qs = np.quantile(values.to_numpy(float), QUANTILES, method="linear")
            sub_qs = np.quantile(grouped_subset.get_group(group_key).to_numpy(float), QUANTILES, method="linear")
            diffs_025.append(abs(main_qs[0] - sub_qs[0]))
            diffs_975.append(abs(main_qs[4] - sub_qs[4]))
        rows.append(
            {
                "variable": variable,
                "n_members_main": len(valid_members),
                "n_members_sensitivity": len(keep),
                "excluded_members": len(valid_members) - len(keep),
                "max_abs_q025_diff": float(np.max(diffs_025)) if diffs_025 else 0.0,
                "max_abs_q975_diff": float(np.max(diffs_975)) if diffs_975 else 0.0,
                "mean_abs_q025_diff": float(np.mean(diffs_025)) if diffs_025 else 0.0,
                "mean_abs_q975_diff": float(np.mean(diffs_975)) if diffs_975 else 0.0,
            }
        )
    return pd.DataFrame(rows)


# ── science gate ────────────────────────────────────────────────────────────

def _resolve_science_gate(
    *, run_dir: Path, run_id: str, allow_unvalidated_demo: bool
) -> tuple[bool, dict[str, Any]]:
    """Mirror export_paper_data's gate: upstream artifacts decide, not labels."""
    provenance: dict[str, Any] = {"run_status": None, "quality_report": None, "calibration_finalize": None}
    status_path = run_dir / "run_status.json"
    if status_path.is_file():
        provenance["run_status"] = json.loads(status_path.read_text(encoding="utf-8"))
    if allow_unvalidated_demo:
        return False, provenance

    run_manifest = run_dir / "run_manifest.yaml"
    quality_report = run_dir / "ies_quality" / "ies_run_quality.json"
    finalize = run_dir / "calibration_finalize" / "calibration_finalize.json"
    if not (run_manifest.is_file() and quality_report.is_file() and finalize.is_file()):
        raise ValueError(
            "science_validated export requires run_manifest.yaml, ies_run_quality.json and "
            "calibration_finalize.json from the same run; use --allow-unvalidated-demo for a "
            "labelled DEMO replay"
        )
    manifest_run_id = read_flat_run_manifest_field(run_manifest, "run_id")
    if manifest_run_id != run_id:
        raise ValueError(f"run_manifest run_id {manifest_run_id!r} != {run_id!r}")
    report: QualityReport = load_quality_report(quality_report)
    if report.run_id and report.run_id != run_id:
        raise ValueError(f"quality report run_id {report.run_id!r} != {run_id!r}")
    if report.status == "fail" or not report.process_completed:
        raise ValueError("engineering quality report failed or incomplete; formal export blocked")
    finalize_data = json.loads(finalize.read_text(encoding="utf-8"))
    if finalize_data.get("science_status") != "science_validated" or finalize_data.get("scientific_status") != "validated":
        raise ValueError("calibration_finalize.json does not grant science_validated; formal export blocked")
    provenance["quality_report"] = {
        "path": str(quality_report),
        "sha256": _sha256(quality_report),
        "status": report.status,
        "science_validated": report.science_validated,
    }
    provenance["calibration_finalize"] = {"path": str(finalize), "sha256": _sha256(finalize)}
    return True, provenance


# ── orchestration ───────────────────────────────────────────────────────────

def _parse_season(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("season must be SEASON_ID=BUNDLE_PATH")
    season, path = value.split("=", 1)
    season = season.strip().upper()
    if season not in ALLOWED_SEASON_IDS:
        raise argparse.ArgumentTypeError(
            f"season must be one of {ALLOWED_SEASON_IDS} (25FA is excluded from this bundle)"
        )
    resolved = Path(path).resolve()
    if not resolved.is_dir():
        raise argparse.ArgumentTypeError(f"season bundle not found: {path}")
    return season, resolved


def export_conditional_predictions(
    *,
    run_dir: Path,
    case: str,
    iteration: int,
    calibration_design: Path,
    season_bundles: dict[str, Path],
    treatment_metadata_csv: Path,
    official_dssat: Path,
    out_dir: Path,
    workers: int,
    member_limit: int | None,
    member_list: list[str] | None,
    verify_members: int,
    allow_unvalidated_demo: bool,
    replay_root_base: Path | None = None,
) -> Path:
    run_dir = run_dir.resolve()
    if not run_dir.is_dir():
        raise ValueError(f"run directory not found: {run_dir}")
    par_csv = run_dir / f"{case}.{iteration}.par.csv"
    member_status_csv = run_dir / "ies_quality" / f"{case}.member_status.csv"
    phi_csv = run_dir / f"{case}.phi.actual.csv"
    tpl_csv = run_dir / f"{case}_params.csv.tpl"
    for path, label in (
        (par_csv, "parameter ensemble"),
        (member_status_csv, "member status"),
        (phi_csv, "phi history"),
        (tpl_csv, "parameter template"),
    ):
        if not path.is_file():
            raise ValueError(f"{label} not found: {path}")

    run_manifest = run_dir / "run_manifest.yaml"
    run_id = read_flat_run_manifest_field(run_manifest, "run_id") or case
    science_validated, science_provenance = _resolve_science_gate(
        run_dir=run_dir, run_id=run_id, allow_unvalidated_demo=allow_unvalidated_demo
    )
    data_status = "science_validated" if science_validated else "legacy_layout_demo"

    metadata = load_two_season_metadata(treatment_metadata_csv)
    environment = verify_replay_environment(
        run_dir=run_dir,
        official_dssat=official_dssat,
        calibration_design=calibration_design.resolve(),
        season_bundles=season_bundles,
        case=case,
    )

    # Role freeze cross-check (plan §10 gate 3): the frozen metadata must agree
    # with the calibration design's per-season calibration treatment sets.
    design_data = json.loads(calibration_design.read_text(encoding="utf-8"))
    for season_spec in design_data.get("seasons", []):
        season_id = season_spec["season_id"]
        if season_id not in ALLOWED_SEASON_IDS:
            continue
        design_calibration = {str(int(t)) for t in season_spec.get("treatments", [])}
        metadata_calibration = set(
            metadata.loc[
                (metadata["season_id"] == season_id) & (metadata["dataset_role"] == "calibration"),
                "treatment",
            ].astype(str)
        )
        if design_calibration != metadata_calibration:
            raise ValueError(
                f"{season_id} calibration treatments in frozen metadata {sorted(metadata_calibration)} "
                f"do not match the calibration design {sorted(design_calibration)}"
            )

    ensemble = load_parameter_ensemble(par_csv)
    member_status = load_member_status(member_status_csv)
    member_phi = load_member_phi(phi_csv, iteration)
    name_mapping = build_tpl_name_mapping(tpl_csv)

    retained_rows = member_status[
        (member_status["state"].astype(str) == "retained")
        & (member_status["final_status"].astype(str) == "retained")
    ]
    machine_flagged = {
        str(row.real_name)
        for row in member_status.itertuples(index=False)
        if str(row.state) != "retained" or str(row.final_status) != "retained"
    }
    candidate_members = [
        str(r) for r in ensemble["real_name"].astype(str) if str(r) not in machine_flagged
    ]
    if member_list:
        wanted = [str(m) for m in member_list]
        missing = [m for m in wanted if m not in set(candidate_members)]
        if missing:
            raise ValueError(f"requested members unavailable or machine-flagged: {missing}")
        candidate_members = [m for m in candidate_members if m in set(wanted)]
    elif member_limit is not None:
        candidate_members = candidate_members[:member_limit]
    if not candidate_members:
        raise ValueError("no ensemble members selected for replay")
    high_phi_valid_included = len(machine_flagged & set(candidate_members)) == 0

    replay_root = _replay_sandbox_root(out_dir, replay_root_base or (_PROJECT_ROOT / "workspace" / "_conditional_replay"))
    if replay_root.exists():
        _safe_rmtree(replay_root)
    replay_root.mkdir(parents=True)
    design_path = build_replay_design(
        calibration_design=calibration_design.resolve(),
        metadata=metadata,
        season_bundles=season_bundles,
        case=case,
        out_path=replay_root / "replay_design.json",
    )

    season_specs = []
    for season in ALLOWED_SEASON_IDS:
        roles = {
            str(row.treatment): str(row.dataset_role)
            for row in metadata[metadata["season_id"] == season].itertuples(index=False)
        }
        experiment_code = next(
            str(s["experiment_code"])
            for s in design_data.get("seasons", [])
            if s["season_id"] == season
        )
        season_specs.append(
            {"season_id": season, "experiment_code": experiment_code, "roles": roles}
        )

    verify_set = set(candidate_members[: max(0, verify_members)])
    ensemble_indexed = ensemble.set_index("real_name")
    jobs: list[dict[str, Any]] = []
    for real in candidate_members:
        row = ensemble_indexed.loc[real]
        param_records = [
            (name_mapping.get(column.lower(), column.upper()), float(row[column]))
            for column in ensemble.columns
            if column != "real_name"
        ]
        jobs.append(
            {
                "real_name": real,
                "member_dir": str(replay_root / f"member_{real}"),
                "param_records": param_records,
                "design_path": str(design_path),
                "season_specs": season_specs,
                "dssat_exe_dir": str(environment.dssat_exe.parent),
                "keep_outputs": real in verify_set,
                "run_id": run_id,
                "data_status": data_status,
            }
        )

    print(
        f"[export_conditional] replaying {len(jobs)} members x "
        f"{sum(len(s['roles']) for s in season_specs)} treatment-runs on {workers} workers"
    )
    results: list[dict[str, Any]] = []
    started = time.monotonic()
    mp_context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp_context) as pool:
        futures = {pool.submit(_replay_member, job): job["real_name"] for job in jobs}
        for future in as_completed(futures):
            results.append(future.result())
            done = len(results)
            latest = results[-1]
            print(
                f"[export_conditional] {done}/{len(jobs)} member {latest['real_name']} "
                f"{latest['status']} ({latest['elapsed_s']:.1f}s)"
            )
    elapsed_total = time.monotonic() - started

    ok_results = [r for r in results if r["status"] == "ok"]
    failed_results = [
        {"realization": r["real_name"], "reason": r["reason"]} for r in results if r["status"] != "ok"
    ]
    if not ok_results:
        raise RuntimeError(f"every ensemble member failed; see member logs under {replay_root}")
    valid_rate = len(ok_results) / len(jobs)
    if valid_rate < GLOBAL_MEMBER_RATE_GATE and not allow_unvalidated_demo:
        raise RuntimeError(
            f"global valid member rate {valid_rate:.3f} < {GLOBAL_MEMBER_RATE_GATE}; "
            "formal freezing is blocked — inspect failed members before retrying"
        )
    if valid_rate < GLOBAL_MEMBER_RATE_GATE:
        print(
            f"[export_conditional] WARNING: valid member rate {valid_rate:.3f} below gate "
            f"{GLOBAL_MEMBER_RATE_GATE} (DEMO mode continues; do not report 95% intervals)"
        )

    event_frames = []
    trajectory_frames = []
    for result in ok_results:
        member_events = result["events"]
        member_trajectory = result["trajectory"]
        member_events["realization"] = result["real_name"]
        member_trajectory["realization"] = result["real_name"]
        event_frames.append(member_events)
        trajectory_frames.append(member_trajectory)
    events = pd.concat(event_frames, ignore_index=True)
    trajectory = pd.concat(trajectory_frames, ignore_index=True)

    aggregate = aggregate_replay(
        events=events,
        trajectory=trajectory,
        metadata=metadata,
        candidate_members=[r["real_name"] for r in ok_results],
        run_id=run_id,
        ensemble_iteration=iteration,
        member_phi=member_phi,
        member_status=member_status,
        observed_se_table=load_observed_se(season_bundles),
    )
    sensitivity = compute_interval_sensitivity(
        events=events,
        valid_members=aggregate.valid_members,
        machine_flagged=machine_flagged,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    metadata_out = out_dir / "treatment_metadata_two_season.csv"
    metadata.to_csv(metadata_out, index=False, encoding="utf-8")
    artifacts = [
        _write_csv(aggregate.prediction_summary, out_dir / "conditional_prediction_summary.csv"),
        _write_csv(aggregate.trajectory_summary, out_dir / "conditional_trajectory_summary.csv"),
        _write_csv(aggregate.residual_members, out_dir / "conditional_residual_by_treatment_member.csv"),
        _write_csv(aggregate.member_availability, out_dir / "conditional_member_availability.csv"),
        _write_csv(sensitivity, out_dir / "conditional_interval_sensitivity.csv"),
        metadata_out,
    ]

    coverage = {}
    for season in ALLOWED_SEASON_IDS:
        part = aggregate.prediction_summary[aggregate.prediction_summary["season_id"] == season]
        coverage[season] = {
            "n_treatments": int(part["treatment"].nunique()),
            "treatments": sorted(part["treatment"].astype(str).unique().tolist()),
            "n_event_points": int(len(part)),
        }
    quality_payload = {
        "schema_version": 1,
        "run_id": run_id,
        "case": case,
        "ensemble_iteration": int(iteration),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "interval_semantics": "parameter_conditional_ensemble_only",
        "terminology": (
            "conditional parameter ensemble; 95% conditional-ensemble prediction interval "
            "(not a confidence/credible interval)"
        ),
        "replay_environment": environment.as_dict(),
        "inputs": {
            "parameter_ensemble": {"path": str(par_csv), "sha256": _sha256(par_csv)},
            "member_status": {"path": str(member_status_csv), "sha256": _sha256(member_status_csv)},
            "phi_history": {"path": str(phi_csv), "sha256": _sha256(phi_csv)},
            "parameter_template": {"path": str(tpl_csv), "sha256": _sha256(tpl_csv)},
            "treatment_metadata": {"path": str(treatment_metadata_csv), "sha256": _sha256(treatment_metadata_csv)},
        },
        "members": {
            "n_in_file_non_base": int(len(ensemble)),
            "n_machine_flagged": len(machine_flagged),
            "machine_flagged": sorted(machine_flagged),
            "n_requested": len(jobs),
            "n_run_ok": len(ok_results),
            "n_complete_case": len(aggregate.valid_members),
            "complete_case_members": aggregate.valid_members,
            "failed": failed_results,
            "valid_rate": valid_rate,
            "high_phi_valid_members_included": high_phi_valid_included,
            "global_rate_gate": GLOBAL_MEMBER_RATE_GATE,
        },
        "uniform_member_rule": (
            "every point uses the same global complete-case member set; keys not covered "
            "by all members were dropped"
        ),
        "dropped_incomplete_points": aggregate.dropped_incomplete_points,
        "observed_consistency": "verified_identical_across_members" if aggregate.observed_consistent else "MISMATCH",
        "coverage": coverage,
        "quantiles": {
            "algorithm": "numpy.quantile",
            "method": "linear",
            "numpy_version": np.__version__,
            "pandas_version": pd.__version__,
        },
        "science": {
            "science_validated": science_validated,
            "demo_mode": not science_validated,
            "data_status": data_status,
            "provenance": science_provenance,
        },
        "runtime": {"wall_seconds": elapsed_total, "workers": workers},
        "replay_sandbox_root": str(replay_root),
        "verification_members_retained": {
            real: str(replay_root / f"member_{real}") for real in sorted(verify_set)
        },
    }
    quality_path = out_dir / "conditional_replay_quality.json"
    quality_path.write_text(
        json.dumps(quality_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    artifacts.append(quality_path)

    manifest_payload = {
        "schema_version": 1,
        "bundle_type": "conditional_ensemble_predictions",
        "run_id": run_id,
        "ensemble_iteration": int(iteration),
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_status": data_status,
        "scenario_type": "actual_trial_calibration",
        "interval_semantics": "parameter_conditional_ensemble_only",
        "renderer_contract": "r_conditional_figures_v1",
        "artifacts": [_artifact(path) for path in artifacts],
        "sources": [
            {"path": str(p), "sha256": _sha256(p)}
            for p in (par_csv, member_status_csv, phi_csv, tpl_csv, treatment_metadata_csv.resolve())
        ],
        "selected_members": {
            "n_complete_case": len(aggregate.valid_members),
            "n_requested": len(jobs),
            "demo_subset": member_limit is not None or member_list is not None,
        },
    }
    manifest_path = out_dir / "paper_data_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic conditional-ensemble replay exporter (two spring seasons, all treatments)"
    )
    parser.add_argument("--run-dir", required=True, help="PEST++ run directory of the source calibration")
    parser.add_argument("--case", required=True, help="PEST case (prefix) inside --run-dir")
    parser.add_argument("--iteration", type=int, required=True, help="final ensemble iteration (e.g. 6)")
    parser.add_argument(
        "--calibration-design", required=True,
        help="calibration design JSON; supplies policy ids and bundle manifest hashes to verify",
    )
    parser.add_argument(
        "--season", action="append", type=_parse_season, required=True, metavar="SEASON=BUNDLE",
        help="repeatable; both 25SP and 26SP are required, 25FA is rejected",
    )
    parser.add_argument(
        "--treatment-metadata", required=True,
        help="frozen two-season treatment metadata CSV (water/nitrogen/role authority)",
    )
    parser.add_argument("--official-dssat", required=True, help="official DSCSM048.EXE path used by calibration")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument(
        "--members", type=int, default=None,
        help="DEMO/performance only: replay just the first N members (never report 95% intervals)",
    )
    parser.add_argument(
        "--member-list", default=None,
        help="comma-separated realization ids to replay (overrides --members)",
    )
    parser.add_argument(
        "--verify-members", type=int, default=3,
        help="retain raw member outputs for the first N members (P1 per-value cross-check)",
    )
    parser.add_argument("--allow-unvalidated-demo", action="store_true")
    parser.add_argument(
        "--replay-root", default=None,
        help="short-path sandbox root for member replays (default workspace/_conditional_replay); "
        "kept short because DSSAT's batch FileX field is 93 characters wide",
    )
    args = parser.parse_args(argv)

    season_bundles = dict(args.season)
    if set(season_bundles) != set(ALLOWED_SEASON_IDS):
        parser.error(f"both seasons {ALLOWED_SEASON_IDS} must be provided via repeated --season")
    if args.workers < 1 or args.workers > 16:
        parser.error("--workers must be between 1 and 16")
    if args.members is not None and args.members < 1:
        parser.error("--members must be at least 1")
    member_list = [m.strip() for m in args.member_list.split(",")] if args.member_list else None

    try:
        manifest = export_conditional_predictions(
            run_dir=Path(args.run_dir),
            case=args.case,
            iteration=args.iteration,
            calibration_design=Path(args.calibration_design),
            season_bundles=season_bundles,
            treatment_metadata_csv=Path(args.treatment_metadata),
            official_dssat=Path(args.official_dssat),
            out_dir=Path(args.out_dir),
            workers=args.workers,
            member_limit=args.members,
            member_list=member_list,
            verify_members=args.verify_members,
            allow_unvalidated_demo=args.allow_unvalidated_demo,
            replay_root_base=Path(args.replay_root) if args.replay_root else None,
        )
    except (ValueError, RuntimeError, ScientificQualityError) as exc:
        parser.error(str(exc))
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
