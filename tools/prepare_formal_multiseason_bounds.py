"""Prepare the reviewable multi-season eggplant genetic-SA bounds proposal.

The tool deliberately writes only to ``bounds_proposals``.  It does not freeze
the proposal or start DSSAT.  Formal execution still requires three audited
season bundles and explicit approval of the generated parameter domain.
"""

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


TEMPERATURE_RANGES = {
    **{name: (8.0, 12.0) for name in ("TB1", "TB2", "TB3")},
    **{name: (20.0, 27.5) for name in ("TO11", "TO12", "TO13")},
    **{name: (28.0, 33.0) for name in ("TO21", "TO22", "TO23")},
    **{name: (34.0, 45.0) for name in ("TM1", "TM2", "TM3")},
}

DYNAMIC_PARTITION_RANGES = {
    "XMAGE": (8.0, 30.0),
    "XFPHT": (35.0, 70.0),
    "XFINT": (0.12, 0.35),
}


def _one_index(frame: pd.DataFrame, name: str) -> int:
    matches = frame.index[frame["name"].astype(str).str.upper() == name]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {name} row, found {len(matches)}")
    return int(matches[0])


def _set_active_range(
    frame: pd.DataFrame,
    name: str,
    lower: float,
    upper: float,
    *,
    initial: float | None = None,
    role: str,
    evidence: str,
) -> None:
    index = _one_index(frame, name)
    init = float(frame.at[index, "init"] if initial is None else initial)
    if not lower <= init <= upper:
        raise ValueError(f"{name} initial {init:g} is outside [{lower:g}, {upper:g}]")
    frame.loc[index, ["init", "lower", "upper", "status"]] = [init, lower, upper, "active"]
    frame.at[index, "decision_role"] = role
    frame.at[index, "evidence_basis"] = evidence
    frame.at[index, "review_note"] = evidence


def _fix(
    frame: pd.DataFrame,
    name: str,
    value: float,
    *,
    role: str,
    evidence: str,
) -> None:
    index = _one_index(frame, name)
    frame.loc[index, ["init", "lower", "upper", "status"]] = [value, value, value, "fixed"]
    frame.at[index, "decision_role"] = role
    frame.at[index, "evidence_basis"] = evidence
    frame.at[index, "review_note"] = evidence


def build_proposal(source: Path, input_dir: Path, output: Path) -> pd.DataFrame:
    summary, findings = validate_input_bundle(input_dir)
    errors = [item for item in findings if item.severity == "error"]
    if errors:
        rendered = "; ".join(f"{item.code}: {item.message}" for item in errors)
        raise ValueError(f"Input bundle failed validation: {rendered}")

    frame = pd.read_csv(source, encoding="utf-8-sig")
    frame["decision_role"] = "core_genetic_screen"
    frame["evidence_basis"] = "Inherited as a proposal candidate; requires final per-parameter review"

    for name, (lower, upper) in TEMPERATURE_RANGES.items():
        _set_active_range(
            frame,
            name,
            lower,
            upper,
            role="multiseason_cardinal_temperature",
            evidence=(
                "Eggplant literature supports Tb about 10-11 C and an optimum/ceiling region around "
                "22-32/35 C; bounds also retain the modified CROPGRO-Tomato baselines and guarantee "
                "TB < TO1 < TO2 < TM without post-sampling clipping"
            ),
        )

    for name, (lower, upper) in DYNAMIC_PARTITION_RANGES.items():
        _set_active_range(
            frame,
            name,
            lower,
            upper,
            role="dynamic_fruit_partition_probe",
            evidence=(
                "Covers the modified tomato baseline and DSSAT strawberry dynamic-partition reference; "
                "rectangular bounds guarantee XMAGE < XFPHT for every independent sample"
            ),
        )

    _set_active_range(
        frame,
        "EM-V1",
        38.0,
        40.0,
        initial=39.3,
        role="multiseason_phenology_valid_domain",
        evidence=(
            "The TM0001 template baseline is 39.3. Deterministic three-season forward checks "
            "showed EM-V1 <=37 produced missing anthesis (ADAPS=-99), while 38-40 retained "
            "finite anthesis dates; the formal SA domain is restricted to the valid regime"
        ),
    )

    _set_active_range(
        frame,
        "FL-VS",
        100.0,
        140.0,
        initial=120.0,
        role="indeterminate_structure_probe",
        evidence=(
            "User-approved 100-140 photothermal-day structural probe for an indeterminate eggplant; "
            "calibration is prohibited unless last-leaf or terminal-growth observations identify it"
        ),
    )

    _fix(
        frame,
        "FRCNOD",
        0.05,
        role="nonlegume_excluded",
        evidence="Root-nodule allocation parameter; fixed and excluded for non-legume eggplant with SYMBI=N",
    )
    frame.at[_one_index(frame, "FRCNOD"), "pargp"] = "SPE_Nodule"
    for name in ("SD-PM", "FL-LF"):
        _fix(
            frame,
            name,
            400.0,
            role="indeterminate_structure_fixed",
            evidence=(
                "Value 400 represents the retained indeterminate/continuing-growth structure; "
                "do not sample a continuous mixture of determinate and indeterminate regimes"
            ),
        )

    soil_mask = frame["location"].astype(str).str.upper().isin({"SOIL", "IC", "INIT"})
    frame.loc[soil_mask, "decision_role"] = "measured_environment_fixed"
    frame.loc[soil_mask, "evidence_basis"] = (
        "Measured environmental or initial-condition input; fixed in the primary genetic SA. "
        "Any narrow nuisance analysis must be separate and measurement-error based."
    )
    frame.loc[soil_mask, "review_note"] = frame.loc[soil_mask, "evidence_basis"]

    if (frame.loc[soil_mask, "status"].astype(str).str.lower() == "active").any():
        raise ValueError("SOIL/IC parameters must not be active in the primary genetic proposal")

    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False, encoding="utf-8-sig")
    assert_valid_frozen_bounds(output)

    manifest = input_dir / "input_manifest.json"
    active = frame[frame["status"].astype(str).str.lower() == "active"]
    metadata = [
        f'proposal_id: "{output.stem}"',
        'crop: "eggplant"',
        f'created_at: "{datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}"',
        'review_status: "proposed"',
        'ready_for_formal_run: false',
        f'derived_from: "{source.name}"',
        f'derived_from_sha256: "{sha256_file(source)}"',
        f'experiment_bundle_available: "{input_dir.name}"',
        f'input_manifest_sha256: "{sha256_file(manifest)}"',
        'required_season_design: "two spring seasons plus one autumn season"',
        'available_audited_season_count: 3',
        'required_audited_season_count: 3',
        f'proposal_sha256: "{sha256_file(output)}"',
        f"parameter_count: {len(frame)}",
        f"active_parameter_count: {len(active)}",
        f"active_temperature_parameter_count: {active['name'].isin(TEMPERATURE_RANGES).sum()}",
        f"active_soil_or_ic_count: {active['location'].astype(str).str.upper().isin({'SOIL', 'IC', 'INIT'}).sum()}",
        'soil_policy: "fixed in primary genetic SA; optional narrow nuisance analysis is separate"',
        'fl_vs_policy: "SA probe 100-140; calibrate only if terminal-growth observations identify the coefficient"',
        'stage_order_policy: "independent rectangular ranges must guarantee XMAGE < XFPHT"',
        'temperature_order_policy: "independent rectangular ranges must guarantee TB < TO1 < TO2 < TM"',
        'references:',
        '  - "https://www.researchgate.net/publication/269708910_Estimation_of_leaf_number_of_eggplant_using_thermal_time_model"',
        '  - "https://journals.ashs.org/downloadpdf/journals/hortsci/47/8/article-p1038.pdf"',
        '  - "https://doi.org/10.1016/j.scienta.2021.110538"',
        '  - "https://doi.org/10.1007/s11119-023-10087-9"',
        'notes: "Three audited season bundles are available; proposal still requires explicit review before freezing"',
        "",
    ]
    output.with_suffix(".yaml").write_text("\n".join(metadata), encoding="utf-8")
    return frame


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    output = Path(args.out).resolve()
    if output.exists() or output.with_suffix(".yaml").exists():
        parser.error(f"Refusing to overwrite existing proposal: {output}")
    frame = build_proposal(Path(args.source).resolve(), Path(args.input_dir).resolve(), output)
    active = frame[frame["status"].astype(str).str.lower() == "active"]
    print(f"Proposal: {output}")
    print(f"Rows: {len(frame)}; active: {len(active)}; temperature: {active['name'].isin(TEMPERATURE_RANGES).sum()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
