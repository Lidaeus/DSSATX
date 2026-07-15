"""Bind reviewed genotype ranges to one versioned experiment input bundle."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.experiment_inputs import validate_input_bundle
from src.common.param_registry import assert_valid_frozen_bounds
from src.common.project import sha256_file


def _row(name: str, value: float, group: str, location: str, target: str, note: str, status: str = "fixed") -> dict[str, object]:
    return {
        "name": name,
        "init": value,
        "lower": value,
        "upper": value,
        "status": status,
        "pargp": group,
        "location": location,
        "file": target,
        "cultivar": "TM0008",
        "ecotype": "TM0001",
        "mode": "both",
        "review_note": note,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create experiment-bound P1 proposal from approved genotype ranges")
    parser.add_argument("--source", required=True)
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    source = Path(args.source).resolve()
    input_dir = Path(args.input_dir).resolve()
    output = Path(args.out).resolve()
    if output.exists() or output.with_suffix(".yaml").exists():
        parser.error(f"Refusing to overwrite: {output}")
    summary, findings = validate_input_bundle(input_dir)
    errors = [item for item in findings if item.severity == "error"]
    if errors:
        parser.error("Input bundle failed: " + "; ".join(item.message for item in errors))

    frame = pd.read_csv(source, encoding="utf-8-sig")
    location = frame["location"].astype(str).str.strip().str.upper()
    retained = frame[~location.isin({"SOIL", "IC", "INIT"})].copy()
    retained["review_note"] = retained["review_note"].astype(str).str.replace(
        "requires user review", "approved by user on 2026-07-15", regex=False
    )
    relationship_ranges = {"XMAGE": (5.0, 20.0), "XFPHT": (25.0, 40.0)}
    for name, (lower, upper) in relationship_ranges.items():
        matches = retained.index[retained["name"].astype(str).str.upper() == name]
        if len(matches) != 1:
            parser.error(f"Expected exactly one {name} row, found {len(matches)}")
        index = matches[0]
        initial = float(retained.at[index, "init"])
        if not lower <= initial <= upper:
            parser.error(f"{name} initial {initial:g} is outside [{lower:g}, {upper:g}]")
        retained.at[index, "lower"] = lower
        retained.at[index, "upper"] = upper
        retained.at[index, "review_note"] = (
            "Range separated after formal preflight so every Morris sample preserves XMAGE < XFPHT"
        )
    profile = summary["soil_profile"]
    nuisance: list[dict[str, object]] = []
    surface = profile["surface"]
    for name in ("SALB", "SLDR", "SLRO"):
        nuisance.append(_row(f"SOIL_{name}", float(surface[name]), "SOIL_SurfaceHydro", "SOIL", "SOIL.SOL", "Fixed to versioned experiment soil profile"))
    groups = {
        "SLOC": "SOIL_Chemical",
        "SBDM": "SOIL_Physical",
        "SLLL": "SOIL_WaterRetention",
        "SDUL": "SOIL_WaterRetention",
        "SSAT": "SOIL_WaterRetention",
    }
    for layer_index, layer in enumerate(profile["layers"], start=1):
        for field, group in groups.items():
            nuisance.append(
                _row(
                    f"SOIL_{field}_{layer_index:02d}",
                    float(layer[field]),
                    group,
                    "SOIL",
                    "SOIL.SOL",
                    f"Fixed to soil {summary['soil_id']} layer boundary {layer['SLB']:g} cm",
                )
            )

    factors = summary["treatment_factors"]
    initial = summary["initial_conditions"]
    for treatment in summary["treatments"]:
        factor = factors.get(treatment) or factors.get(str(treatment))
        ic_id = int(factor["IC"])
        for layer_index, layer in enumerate(initial.get(ic_id) or initial.get(str(ic_id)), start=1):
            nuisance.append(
                _row(
                    f"IC_SH2O_TN{treatment:02d}_L{layer_index:02d}",
                    float(layer["sh2o"]),
                    "IC_InitialWater",
                    "IC",
                    summary["filex"],
                    f"Disabled: treatment-specific IC{ic_id}, {layer['depth']:g} cm; not a shared calibration parameter",
                    status="disabled",
                )
            )
    result = pd.concat([retained, pd.DataFrame(nuisance)], ignore_index=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False, encoding="utf-8-sig")
    assert_valid_frozen_bounds(output)
    manifest = input_dir / "input_manifest.json"
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    output.with_suffix(".yaml").write_text(
        "\n".join(
            [
                f'proposal_id: "{output.stem}"',
                'crop: "eggplant"',
                f'created_at: "{created_at}"',
                'review_status: "approved"',
                f'derived_from: "{source.name}"',
                f'derived_from_sha256: "{sha256_file(source)}"',
                f'experiment_bundle: "{input_dir.name}"',
                f'input_manifest_sha256: "{sha256_file(manifest)}"',
                f'proposal_sha256: "{sha256_file(output)}"',
                f"parameter_count: {len(result)}",
                f"active_parameter_count: {(result['status'].str.lower() == 'active').sum()}",
                f"fixed_soil_parameter_count: {sum(row['location'] == 'SOIL' for row in nuisance)}",
                f"disabled_treatment_ic_count: {sum(row['location'] == 'IC' for row in nuisance)}",
                'approval_basis: "User approved boundary changes in project thread on 2026-07-15"',
                'notes: "Genotype ranges approved; soil fixed to input bundle; treatment-specific IC explicitly disabled"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"Proposal: {output}")
    print(f"Rows: {len(result)}; active: {(result['status'].str.lower() == 'active').sum()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
