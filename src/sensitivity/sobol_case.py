"""Build an isolated, approval-gated PESTPP-SEN Sobol case."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd
import pyemu

from src.common.project import sha256_file
from src.sensitivity.sa_build_sen_case import build_case


SOBOL_RUN_TYPES = {
    "sensitivity_sobol_preflight_case",
    "sensitivity_sobol_formal_case",
}


def load_approved_topk(approval_json: str | Path) -> tuple[dict[str, Any], pd.DataFrame, Path]:
    metadata_path = Path(approval_json).resolve()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("review_status") != "approved":
        raise ValueError("Sobol Top-K metadata must have review_status=approved")
    csv_value = metadata.get("approved_topk_csv")
    if not csv_value:
        raise ValueError("Sobol Top-K metadata does not name approved_topk_csv")
    csv_path = Path(csv_value)
    if not csv_path.is_absolute():
        csv_path = metadata_path.parent / csv_path
    csv_path = csv_path.resolve()
    if not csv_path.is_file():
        raise FileNotFoundError(csv_path)
    expected_hash = str(metadata.get("approved_topk_csv_sha256", "")).lower()
    actual_hash = sha256_file(csv_path)
    if not expected_hash or actual_hash != expected_hash:
        raise ValueError("Approved Sobol Top-K CSV hash does not match metadata")

    frame = pd.read_csv(csv_path)
    required = {"parameter", "selection_class", "approval_status"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Approved Sobol Top-K CSV is missing columns: {sorted(missing)}")
    frame["parameter"] = frame["parameter"].astype(str).str.strip().str.upper()
    if frame.empty or frame["parameter"].duplicated().any():
        raise ValueError("Approved Sobol Top-K parameters must be non-empty and unique")
    if set(frame["approval_status"].astype(str).str.lower()) != {"approved"}:
        raise ValueError("Every Sobol Top-K parameter must be explicitly approved")
    expected_count = int(metadata.get("approved_parameter_count", 0) or 0)
    if expected_count <= 0 or len(frame) != expected_count:
        raise ValueError("Approved Sobol Top-K parameter count does not match metadata")
    return metadata, frame, csv_path


def _append_manifest(path: Path, values: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}: {value}\n")


def build_sobol_case(
    *,
    bounds_csv: str | Path,
    approval_json: str | Path,
    case_dir: str | Path,
    workspace_dir: str | Path,
    output_profile: str | Path,
    input_dir: str | Path,
    samples: int,
    random_seed: int,
    run_type: str = "sensitivity_sobol_preflight_case",
    cultivar: str = "TM0008",
    case_name: str = "sa_sen_sobol",
) -> Path:
    if run_type not in SOBOL_RUN_TYPES:
        raise ValueError(f"Unsupported Sobol run type: {run_type}")
    samples = int(samples)
    if samples < 2:
        raise ValueError("Sobol samples must be at least 2")
    if run_type == "sensitivity_sobol_preflight_case" and samples > 16:
        raise ValueError("Sobol preflight is limited to at most 16 base samples")
    if run_type == "sensitivity_sobol_formal_case" and samples < 32:
        raise ValueError("Formal Sobol requires at least 32 base samples")

    bounds_path = Path(bounds_csv).resolve()
    profile_path = Path(output_profile).resolve()
    input_path = Path(input_dir).resolve()
    destination = Path(case_dir).resolve()
    metadata, approved, approved_csv = load_approved_topk(approval_json)

    expected = {
        "bounds_sha256": sha256_file(bounds_path),
        "output_profile_sha256": sha256_file(profile_path),
        "input_manifest_sha256": sha256_file(input_path / "input_manifest.json"),
    }
    for key, actual in expected.items():
        approved_hash = str(metadata.get(key, "")).lower()
        if not approved_hash or approved_hash != actual:
            raise ValueError(f"Sobol approval metadata {key} does not match selected input")

    bounds = pd.read_csv(bounds_path)
    bounds["name"] = bounds["name"].astype(str).str.strip().str.upper()
    active = set(
        bounds.loc[bounds["status"].astype(str).str.lower() == "active", "name"]
    )
    selected = set(approved["parameter"])
    missing = selected - active
    if missing:
        raise ValueError(f"Approved Sobol parameters are not active in frozen bounds: {sorted(missing)}")

    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"Sobol case directory must be new or empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    build_case(
        str(bounds_path),
        case_dir=str(destination),
        workspace_dir=str(Path(workspace_dir).resolve()),
        cultivar=cultivar,
        morris_r=2,
        morris_p=4,
        random_seed=int(random_seed),
        output_profile=str(profile_path),
        input_dir=str(input_path),
        run_type=run_type,
    )

    source_pst = destination / "sa_sen_morris.pst"
    pst = pyemu.Pst(str(source_pst))
    available = {str(name).strip().upper() for name in pst.parameter_data.parnme}
    if selected - available:
        raise ValueError(f"Approved parameters are absent from generated PEST case: {sorted(selected - available)}")
    status_rows: list[dict[str, Any]] = []
    for parameter in pst.parameter_data.parnme:
        canonical = str(parameter).strip().upper()
        is_selected = canonical in selected
        if is_selected:
            pst.parameter_data.loc[parameter, "partrans"] = "none"
        else:
            value = float(pst.parameter_data.loc[parameter, "parval1"])
            pst.parameter_data.loc[parameter, "partrans"] = "fixed"
            pst.parameter_data.loc[parameter, "parlbnd"] = value
            pst.parameter_data.loc[parameter, "parubnd"] = value
        status_rows.append(
            {
                "parameter": canonical,
                "sobol_status": "active" if is_selected else "fixed",
                "init": float(pst.parameter_data.loc[parameter, "parval1"]),
                "lower": float(pst.parameter_data.loc[parameter, "parlbnd"]),
                "upper": float(pst.parameter_data.loc[parameter, "parubnd"]),
            }
        )

    pst.pestpp_options["gsa_method"] = "sobol"
    pst.pestpp_options["gsa_sobol_samples"] = samples
    pst.pestpp_options["gsa_sobol_par_dist"] = "unif"
    pst.pestpp_options["rand_seed"] = int(random_seed)
    output_pst = destination / f"{case_name}.pst"
    pst.write(str(output_pst))

    verification = pyemu.Pst(str(output_pst))
    adjustable = {
        str(name).strip().upper()
        for name, row in verification.parameter_data.iterrows()
        if str(row["partrans"]).lower() != "fixed"
    }
    if adjustable != selected:
        raise RuntimeError("Written Sobol PST does not preserve the approved parameter set")

    pd.DataFrame(status_rows).sort_values("parameter").to_csv(
        destination / "sobol_parameters.csv", index=False, encoding="utf-8-sig"
    )
    shutil.copyfile(approved_csv, destination / "sobol_approval.csv")
    shutil.copyfile(Path(approval_json).resolve(), destination / "sobol_approval.json")
    expected_model_runs = samples * (len(selected) + 2)
    _append_manifest(
        destination / "run_manifest.yaml",
        {
            "sensitivity_method": "sobol",
            "sobol_approval_id": metadata["approval_id"],
            "sobol_approval_json_sha256": sha256_file(Path(approval_json).resolve()),
            "sobol_topk_sha256": sha256_file(approved_csv),
            "sobol_parameter_count": len(selected),
            "sobol_samples": samples,
            "sobol_expected_model_runs": expected_model_runs,
            "sobol_parameter_distribution": "uniform",
            "sobol_case": case_name,
            "sobol_pst_sha256": sha256_file(output_pst),
        },
    )
    return output_pst
