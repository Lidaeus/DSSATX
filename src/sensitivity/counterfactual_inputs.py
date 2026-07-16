"""Build sensitivity-only counterfactual experiment bundles.

Calibration must continue to use the observed treatment-specific initial
conditions.  This module creates a separate, traceable bundle in which the
selected factorial treatments share one initial soil-water and mineral-N
profile, so only the irrigation (MI) and fertilizer (MF) factors differ.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from src.common.experiment_inputs import (
    batch_entries,
    findings_as_dicts,
    parse_filex,
    validate_input_bundle,
)
from src.sensitivity.treatment_factor_attribution import (
    _replace_tokens,
    replace_treatment_factors,
)


CORE_TREATMENTS = (2, 3, 4, 5, 10, 11, 12, 13)
INITIAL_FIELDS = ("sh2o", "snh4", "sno3")


def pooled_median_initial_profile(
    filex_path: str | Path,
    treatments: tuple[int, ...] = CORE_TREATMENTS,
) -> list[dict[str, float]]:
    """Return the depth-wise median profile across selected treatments."""

    parsed = parse_filex(filex_path)
    rows_by_treatment: dict[int, dict[float, dict[str, float]]] = {}
    for treatment in treatments:
        factors = parsed["treatments"].get(int(treatment))
        if not factors:
            raise KeyError(f"Treatment TN{treatment} is absent from FileX")
        ic = int(factors["IC"])
        rows = parsed["initial_conditions"].get(ic, [])
        if not rows:
            raise KeyError(f"Treatment TN{treatment} references missing IC{ic}")
        rows_by_treatment[int(treatment)] = {float(row["depth"]): row for row in rows}

    depth_sets = {tuple(sorted(rows)) for rows in rows_by_treatment.values()}
    if len(depth_sets) != 1:
        raise ValueError("Selected treatments do not share identical IC layer depths")

    profile: list[dict[str, float]] = []
    for depth in next(iter(depth_sets)):
        row: dict[str, float] = {"depth": float(depth)}
        for field in INITIAL_FIELDS:
            row[field] = round(
                float(median(rows_by_treatment[treatment][depth][field] for treatment in treatments)),
                6,
            )
        profile.append(row)
    return profile


def replace_initial_profile(
    text: str,
    target_ic: int,
    profile: list[dict[str, float]],
) -> str:
    """Replace SH2O/SNH4/SNO3 values for one IC level without changing layout."""

    source = {float(row["depth"]): row for row in profile}
    lines = text.splitlines()
    in_initial = False
    layer_header = False
    changed_depths: set[float] = set()
    for index, line in enumerate(lines):
        upper = line.strip().upper()
        if upper.startswith("*INITIAL CONDITIONS"):
            in_initial = True
            continue
        if in_initial and line.startswith("*"):
            break
        if not in_initial:
            continue
        if upper.startswith("@C") and "ICBL" in upper and "SH2O" in upper:
            layer_header = True
            continue
        if upper.startswith("@C"):
            layer_header = False
            continue
        tokens = line.split()
        if not layer_header or len(tokens) < 5:
            continue
        try:
            row_ic = int(tokens[0])
            depth = float(tokens[1])
        except ValueError:
            continue
        if row_ic != int(target_ic):
            continue
        if depth not in source:
            raise ValueError(f"Counterfactual profile lacks IC{target_ic} depth {depth:g}")
        row = source[depth]

        def field(value: float) -> str:
            rendered = format(float(value), ".6g")
            if rendered.startswith("0."):
                rendered = rendered[1:]
            elif rendered.startswith("-0."):
                rendered = "-." + rendered[3:]
            if len(rendered) > 6:
                raise ValueError(f"Initial-condition value does not fit FileX width: {value}")
            return rendered.rjust(6)

        lines[index] = (
            f"{row_ic:3d}{int(depth):6d}"
            f"{field(row['sh2o'])}{field(row['snh4'])}{field(row['sno3'])}"
        )
        changed_depths.add(depth)
    if changed_depths != set(source):
        raise ValueError(
            f"Expected to replace depths {sorted(source)}, changed {sorted(changed_depths)}"
        )
    return "\n".join(lines) + "\n"


def _filtered_batch(text: str, treatments: tuple[int, ...]) -> str:
    keep = set(int(value) for value in treatments)
    lines: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped and not stripped.startswith(("$", "!", "@", "*")):
            parts = stripped.split()
            if parts and Path(parts[0]).suffix.upper() == ".TMX":
                try:
                    if int(float(parts[1])) not in keep:
                        continue
                except (IndexError, ValueError):
                    pass
        lines.append(raw)
    return "\n".join(lines) + "\n"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_counterfactual_bundle(
    source_dir: str | Path,
    output_dir: str | Path,
    *,
    treatments: tuple[int, ...] = CORE_TREATMENTS,
    common_ic: int = 2,
) -> dict[str, object]:
    """Create and validate a sensitivity-only controlled experiment bundle."""

    source = Path(source_dir).resolve()
    output = Path(output_dir).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Refusing to overwrite non-empty bundle: {output}")
    source_summary, source_findings = validate_input_bundle(source)
    source_errors = [item for item in source_findings if item.severity == "error"]
    if source_errors:
        raise ValueError("Source input bundle does not pass validation")

    source_batch = source / "DSSBatch.v48"
    entries = batch_entries(source_batch)
    if not entries:
        raise ValueError("Source batch contains no treatments")
    filex_name = entries[0][0]
    source_filex = source / filex_name
    profile = pooled_median_initial_profile(source_filex, treatments)

    output.mkdir(parents=True, exist_ok=True)
    for path in source.iterdir():
        if path.is_file() and path.name not in {filex_name, "DSSBatch.v48", "input_manifest.json"}:
            shutil.copy2(path, output / path.name)

    text = source_filex.read_text(encoding="utf-8")
    for treatment in treatments:
        text = replace_treatment_factors(text, treatment, {"IC": int(common_ic)})
    # DSSAT may validate every IC block while reading FileX, including blocks
    # not referenced by the selected batch.  Normalize all retained blocks so
    # an unused legacy profile cannot contaminate or invalidate the scenario.
    for ic_level in sorted(source_summary["initial_conditions"]):
        text = replace_initial_profile(text, int(ic_level), profile)
    (output / filex_name).write_text(text, encoding="utf-8", newline="\n")
    (output / "DSSBatch.v48").write_text(
        _filtered_batch(source_batch.read_text(encoding="utf-8"), treatments),
        encoding="utf-8",
        newline="\n",
    )

    summary, findings = validate_input_bundle(output)
    errors = [item for item in findings if item.severity == "error"]
    if errors:
        raise ValueError("Generated counterfactual bundle failed validation")
    if tuple(summary["treatments"]) != tuple(sorted(treatments)):
        raise ValueError("Generated batch treatment set differs from the approved factorial design")
    factors = summary["treatment_factors"]
    if {int(factors[treatment]["IC"]) for treatment in treatments} != {int(common_ic)}:
        raise ValueError("Generated treatments do not share one common IC level")

    source_manifest = source / "input_manifest.json"
    files = []
    for path in sorted(item for item in output.iterdir() if item.is_file()):
        if path.name == "input_manifest.json":
            continue
        files.append({"name": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size})
    manifest: dict[str, object] = {
        "bundle_id": output.name,
        "scenario_type": "controlled_counterfactual_sensitivity_input",
        "intended_use": "genetic_parameter_sensitivity_analysis_only",
        "prohibited_use": ["parameter_calibration", "validation_against_observed_treatment_initial_conditions"],
        "derived_from_bundle": source.name,
        "source_manifest_sha256": _sha256(source_manifest) if source_manifest.is_file() else None,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "approved_factorial_treatments": list(treatments),
        "controlled_factors": {
            "common_initial_condition_level": int(common_ic),
            "components": ["SH2O", "SNH4", "SNO3"],
            "aggregation": "depth-wise median across the eight approved factorial treatments",
            "source_treatments": list(treatments),
            "normalized_filex_ic_levels": sorted(int(value) for value in source_summary["initial_conditions"]),
            "profile": profile,
        },
        "varying_management_factors": ["MI", "MF"],
        "unchanged_from_source": ["weather", "soil profile", "cultivar", "planting", "irrigation schedules", "fertilizer schedules", "observation files"],
        "files": files,
        "summary": summary,
        "findings": findings_as_dicts(findings),
        "science_status": "counterfactual_pass_with_warnings" if findings else "counterfactual_pass",
    }
    (output / "input_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a controlled sensitivity-only FileX bundle")
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--common-ic", type=int, default=2)
    args = parser.parse_args()
    manifest = build_counterfactual_bundle(
        args.source_dir,
        args.out_dir,
        common_ic=args.common_ic,
    )
    print(json.dumps({"bundle_id": manifest["bundle_id"], "science_status": manifest["science_status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
