"""Validated, stage-aware calibration design configuration.

The design file is deliberately small and declarative.  It controls the
parameter release and the observations that receive non-zero PEST weights;
validation and diagnostic treatments remain in the files for traceability but
cannot enter Phi.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import pyemu

from src.common.project import PROJECT_ROOT


@dataclass(frozen=True)
class DesignSpec:
    path: Path
    design_table_id: str
    stage: str
    stage_config: Mapping[str, Any]
    active_params: tuple[str, ...]
    treatment_roles: Mapping[str, tuple[int, ...]]
    observation: Mapping[str, Any]
    validation_split_id: str

    @property
    def calibration_treatments(self) -> set[int]:
        return set(self.treatment_roles.get("calibration", ()))

    @property
    def validation_treatments(self) -> set[int]:
        return set(self.treatment_roles.get("validation", ()))

    @property
    def diagnostic_treatments(self) -> set[int]:
        return set(self.treatment_roles.get("diagnostic", ()))


def _resolve_split(design_path: Path, split_id: str) -> Path:
    candidates = [
        design_path.parent / f"{split_id}.json",
        design_path.parent / f"{split_id.replace('_split_', '_validation_split_')}.json",
        PROJECT_ROOT / "configs" / "runs" / f"{split_id}.json",
        PROJECT_ROOT / "configs" / "runs" / f"{split_id.replace('_split_', '_validation_split_')}.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"validation split {split_id!r} was not found")


def _reject_validation_selection(stage_name: str, stage_cfg: Mapping[str, Any]) -> None:
    """Reject the old S4 rule which selected parameters using validation."""
    if stage_name.upper() != "S4":
        return
    text = json.dumps(stage_cfg, ensure_ascii=False).lower()
    forbidden = (
        "improved validation" in text
        or "improve validation" in text
        or "validation result" in text
        or "select validation" in text
    )
    if forbidden:
        raise ValueError(
            "S4 design must be calibration-only: validation may be inspected only "
            "after the joint parameter set is frozen"
        )


def load_design_config(path: str | Path, stage: str) -> DesignSpec:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"design config not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("design config must be a JSON object")
    stage_name = str(stage or "").strip().upper()
    stages = payload.get("stages")
    if not isinstance(stages, Mapping) or stage_name not in stages:
        raise ValueError(f"design config has no stage {stage_name!r}")
    stage_cfg = stages[stage_name]
    if not isinstance(stage_cfg, Mapping):
        raise ValueError(f"stage {stage_name} must be an object")
    _reject_validation_selection(stage_name, stage_cfg)
    active = stage_cfg.get("active_params")
    if not isinstance(active, list) or not active or not all(str(x).strip() for x in active):
        raise ValueError(
            f"stage {stage_name} active_params must be a non-empty list; "
            "dynamic parameter selection is not allowed in a build"
        )
    active_params = tuple(dict.fromkeys(str(x).strip().upper() for x in active))

    split_id = str(payload.get("validation_split_id", "")).strip()
    if not split_id:
        raise ValueError("design config must declare validation_split_id")
    split_path = _resolve_split(path, split_id)
    split = json.loads(split_path.read_text(encoding="utf-8"))
    roles = split.get("treatment_roles") if isinstance(split, Mapping) else None
    if not isinstance(roles, Mapping):
        raise ValueError(f"validation split {split_path} has no treatment_roles")
    normalized_roles: dict[str, tuple[int, ...]] = {}
    for role in ("calibration", "validation", "diagnostic"):
        values = roles.get(role, [])
        if not isinstance(values, list):
            raise ValueError(f"treatment role {role} must be a list")
        normalized_roles[role] = tuple(int(v) for v in values)
    if set().union(*[set(v) for v in normalized_roles.values()]) != set(
        sum((list(v) for v in normalized_roles.values()), [])
    ):
        raise ValueError("treatment roles contain duplicate treatment IDs")

    observation = {
        "outputs": {
            "S1": {"PestEval.OUT": ["ADAP"], "PestTmtGrow.OUT": ["LAID"]},
            "S2": {
                "PestJoint.OUT": ["LAIX", "CNAM"],
                "PestHarvest.OUT": ["PWAD", "PWAI"],
                "PestTmtGrow.OUT": ["LAID", "LWAD", "SWAD"],
            },
            "S3": {
                "PestHarvest.OUT": ["PWAD", "PWAI"],
            },
            "S4": {
                "PestEval.OUT": ["ADAP"],
                "PestJoint.OUT": ["LAIX", "CNAM"],
                "PestHarvest.OUT": ["PWAD", "PWAI"],
                "PestTmtGrow.OUT": ["LAID", "LWAD", "SWAD"],
            },
        }.get(stage_name, {})
    }
    # A future design may provide an explicit observation map, but it must be
    # a map of output basename -> base variable names, never a free-form CLI
    # switch that silently changes the objective.
    explicit_observation = stage_cfg.get("observation_outputs")
    if explicit_observation is not None:
        if not isinstance(explicit_observation, Mapping):
            raise ValueError("observation_outputs must be an object")
        observation = explicit_observation
    diagnostic_outputs = stage_cfg.get("diagnostic_outputs", {})
    if not isinstance(diagnostic_outputs, Mapping):
        raise ValueError("diagnostic_outputs must be an object")

    return DesignSpec(
        path=path,
        design_table_id=str(payload.get("design_table_id", path.stem)),
        stage=stage_name,
        stage_config=stage_cfg,
        active_params=active_params,
        treatment_roles=normalized_roles,
        observation={
            "outputs": observation,
            "diagnostic_outputs": diagnostic_outputs,
            "split_path": str(split_path),
        },
        validation_split_id=split_id,
    )


def apply_parameter_stage(params: list[dict[str, Any]], spec: DesignSpec) -> list[dict[str, Any]]:
    """Release only the declared active parameters to PEST++."""
    by_name = {str(p.get("name", "")).strip().upper(): p for p in params}
    missing = [name for name in spec.active_params if name not in by_name]
    if missing:
        raise ValueError(f"stage {spec.stage} parameters are absent from the template: {', '.join(missing)}")
    fixed_names = tuple(str(x).strip().upper() for x in (spec.stage_config.get("fixed_params") or []))
    missing_fixed = [name for name in fixed_names if name not in by_name]
    if missing_fixed:
        raise ValueError(f"stage {spec.stage} fixed baseline parameters are absent from the template: {', '.join(missing_fixed)}")
    selected = [by_name[name] for name in spec.active_params]
    for name in fixed_names:
        item = dict(by_name[name])
        item["lower"] = item["upper"] = item["init"]
        item["status"] = "fixed"
        selected.append(item)
    return selected


def _run_to_treatment(batch_entries: list[Mapping[str, Any]]) -> dict[int, int]:
    return {int(e["run"]): int(e["tn"]) for e in batch_entries if e.get("tn") is not None}


def apply_observation_stage(outputs: list[dict[str, Any]], spec: DesignSpec,
                            batch_entries: list[Mapping[str, Any]],
                            eval_df: Any = None) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Filter output blocks and calibration treatments before PST creation."""
    output_rules = spec.observation.get("outputs", {})
    run_to_tn = _run_to_treatment(batch_entries)
    calibration = spec.calibration_treatments
    selected: list[dict[str, Any]] = []
    report = {"outputs_selected": 0, "outputs_dropped": 0, "rows_dropped": 0}
    for out in outputs:
        basename = Path(str(out.get("model_out_path", ""))).name
        bases = output_rules.get(basename)
        if bases is None:
            report["outputs_dropped"] += 1
            continue
        item = dict(out)
        item["obs_bases"] = set(str(x).upper() for x in bases)
        df = item.get("df")
        if df is None and eval_df is not None:
            # Joint/evaluation blocks share the evaluation table; materialize
            # a filtered copy so validation rows cannot leak into Phi.
            df = eval_df.copy()
        if df is not None and not df.empty:
            before = len(df)
            if "TN" in df.columns:
                df = df[df["TN"].astype(int).isin(calibration)].copy()
            elif "@RUN" in df.columns and run_to_tn:
                df = df[df["@RUN"].astype(int).map(run_to_tn).isin(calibration)].copy()
            item["df"] = df
            report["rows_dropped"] += before - len(df)
        selected.append(item)
        report["outputs_selected"] += 1
    if not selected:
        raise ValueError(f"stage {spec.stage} selected no observation outputs")
    return selected, report


def write_design_audit(pst_path: str | Path, spec: DesignSpec,
                       batch_entries: list[Mapping[str, Any]], out_path: str | Path) -> Path:
    """Write a row-level audit of treatment role and final Phi weight."""
    pst = pyemu.Pst(str(pst_path))
    run_to_tn = _run_to_treatment(batch_entries)
    rows = []
    for name, row in pst.observation_data.iterrows():
        match = re.search(r"_R(\d+)", str(name), flags=re.IGNORECASE)
        tn = run_to_tn.get(int(match.group(1))) if match else None
        if tn in spec.calibration_treatments:
            role = "calibration"
        elif tn in spec.validation_treatments:
            role = "validation"
        elif tn in spec.diagnostic_treatments:
            role = "diagnostic"
        else:
            role = "unknown"
        rows.append({
            "obsnme": str(name), "obgnme": str(row.obgnme), "treatment": tn,
            "role": role, "weight": float(row.weight),
            "nonzero_phi": bool(float(row.weight) > 0),
        })
    destination = Path(out_path)
    pd.DataFrame(rows).to_csv(destination, index=False)
    return destination
