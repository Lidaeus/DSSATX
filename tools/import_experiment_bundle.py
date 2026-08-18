"""Import and audit one user-defined DSSAT experiment input bundle."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.experiment_inputs import (
    filex_harvest_dates,
    findings_as_dicts,
    management_alignment_findings,
    parse_filex,
    replace_filex_management_sections,
    validate_input_bundle,
)
from src.common.project import sha256_file
from src.sensitivity.treatment_factor_attribution import normalize_fertilizer_level_rows


def _set_weather_coordinates(path: Path, latitude: float, longitude: float) -> None:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    for index, line in enumerate(lines):
        if line.strip().upper().startswith("@ INSI") and index + 1 < len(lines):
            parts = lines[index + 1].split()
            if len(parts) < 3:
                raise ValueError(f"Cannot parse weather site row in {path}")
            parts[1] = f"{latitude:.3f}"
            parts[2] = f"{longitude:.3f}"
            lines[index + 1] = "  " + " ".join(parts)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return
    raise ValueError(f"Cannot find @ INSI weather header in {path}")


def _set_simulation_option(path: Path, option: str, value: str) -> int:
    """Set one FileX simulation option for every OP control row.

    DSSAT parses ``@N OPTIONS`` data rows by **exact fixed-width column
    position** as given by the header row — the same column the option name
    starts in. Re-serializing the entire row (even with the same token values)
    changes spacing and breaks DSSAT's column parser (observed: IPSIM /
    potassium-model error even when all flags are correct). Therefore we change
    ONLY the single character at the option column — every other byte of the
    data row is preserved verbatim, including the original trailing whitespace
    and line ending.
    """

    option = option.strip().upper()
    value = value.strip().upper()
    if len(value) != 1:
        raise ValueError(f"FileX simulation option {option} value must be a single token, got {value!r}")
    raw = path.read_bytes()
    # Detect native newline
    newline = b"\r\n" if b"\r\n" in raw else b"\n"
    newline_str = "\r\n" if b"\r\n" in raw else "\n"
    lines = raw.split(newline)
    header_line: bytes | None = None
    option_col: int | None = None
    changed = 0
    for index, line_bytes in enumerate(lines):
        upper = line_bytes.strip().upper()
        if upper.startswith(b"@N OPTIONS"):
            header_line = line_bytes
            option_col = _find_option_column(header_line, option)
            if option_col is None:
                raise ValueError(f"Cannot locate simulation option {option} in OPTIONS header in {path}")
            continue
        if header_line is not None and upper.startswith(b"@"):
            header_line = None
            option_col = None
            continue
        if header_line is None or option_col is None:
            continue
        stripped = line_bytes.strip()
        if not stripped or stripped.startswith((b"*", b"!")):
            continue
        parts = stripped.split()
        if len(parts) < 2 or parts[1].upper() != b"OP":
            continue
        if option_col >= len(line_bytes):
            # Row too short for the column — pad with spaces, then set value.
            line_bytes = line_bytes.rstrip() + b" " * (option_col - len(line_bytes) + 1)
        chars = bytearray(line_bytes)
        chars[option_col] = ord(value)
        lines[index] = bytes(chars)
        changed += 1
    if changed == 0:
        raise ValueError(f"Cannot find any simulation OPTIONS rows in {path}")
    # Write back using original bytes with the same native newline.
    # On Windows, write_text(newline="\n") still produces \r\n in some
    # codepaths; writing raw bytes avoids all CR translation.
    path.write_bytes(newline.join(lines) + newline)
    return changed


def _find_option_column(header_line: bytes, option: str) -> int | None:
    """Return the byte offset of *option* in the OPTIONS header row.

    The option value in the data row occupies the same byte offset.
    """
    import re

    for match in re.finditer(re.escape(option.encode()), header_line):
        return match.start()
    return None


def _set_experiment_details(path: Path, details: str) -> None:
    """Replace only the FileX experiment-details title line."""

    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if not lines or not lines[0].strip().upper().startswith("*EXP.DETAILS:"):
        raise ValueError(f"Cannot find FileX experiment-details title in {path}")
    lines[0] = f"*EXP.DETAILS: {details.strip()}"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _section_text(path: Path, heading: str) -> str:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.strip().upper().startswith(heading.upper())),
        None,
    )
    if start is None:
        raise ValueError(f"Cannot find {heading} in {path}")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("*")), len(lines))
    return "\n".join(line.rstrip() for line in lines[start:end]).strip()


def _assert_actual_trial_preserved(candidate: Path, reference: Path) -> dict[str, object]:
    """Reject formal bundles that pool measured IC or soil-analysis inputs."""
    candidate_parsed = parse_filex(candidate)
    reference_parsed = parse_filex(reference)
    if candidate_parsed["initial_conditions"] != reference_parsed["initial_conditions"]:
        raise ValueError("Formal bundle changes treatment-specific *INITIAL CONDITIONS")
    candidate_treatments = candidate_parsed["treatments"]
    reference_treatments = reference_parsed["treatments"]
    if set(candidate_treatments) != set(reference_treatments):
        raise ValueError("Formal bundle treatment IDs differ from the actual-trial reference")
    for treatment in sorted(reference_treatments):
        for factor in ("IC", "SA", "MI", "MF"):
            before = reference_treatments[treatment].get(factor)
            after = candidate_treatments[treatment].get(factor)
            if before != after:
                raise ValueError(f"Formal bundle changes TN{treatment} {factor}: {before} -> {after}")
    treatment_count = len(candidate_treatments)
    ic_count = len({values.get("IC") for values in candidate_treatments.values()})
    sa_count = len({values.get("SA") for values in candidate_treatments.values()})
    if ic_count != treatment_count or sa_count != treatment_count:
        raise ValueError(
            "Formal bundle must retain one measured IC and SA level per treatment; "
            f"treatments={treatment_count}, IC={ic_count}, SA={sa_count}"
        )
    section_hashes: dict[str, str] = {}
    for heading in ("*SOIL ANALYSIS", "*INITIAL CONDITIONS"):
        candidate_text = _section_text(candidate, heading)
        reference_text = _section_text(reference, heading)
        if candidate_text != reference_text:
            raise ValueError(f"Formal bundle changes measured {heading} data")
        section_hashes[heading] = hashlib.sha256(candidate_text.encode("utf-8")).hexdigest()
    return {
        "reference_filex": str(reference),
        "reference_filex_sha256": sha256_file(reference),
        "treatment_count": treatment_count,
        "treatment_specific_ic_count": ic_count,
        "treatment_specific_sa_count": sa_count,
        "section_sha256": section_hashes,
    }


def _trim_estimated_harvest_observations(bundle: Path, experiment: str, cutoff: int) -> list[dict[str, object]]:
    """Remove FileT events and invalidate FileA yields after the FileX cutoff."""

    corrections: list[dict[str, object]] = []
    tmt = bundle / f"{experiment}.TMT"
    if tmt.is_file():
        lines = tmt.read_text(encoding="utf-8", errors="ignore").splitlines()
        kept: list[str] = []
        removed = 0
        for line in lines:
            fields = line.split()
            if fields and fields[0].lstrip("+-").isdigit() and len(fields) >= 2:
                try:
                    if int(float(fields[1])) > cutoff:
                        removed += 1
                        continue
                except ValueError:
                    pass
            kept.append(line)
        if removed:
            tmt.write_text("\n".join(kept) + "\n", encoding="utf-8", newline="\n")
            corrections.append({"file": tmt.name, "field": "harvest event date", "removed_rows": removed, "cutoff": cutoff})

    tma = bundle / f"{experiment}.TMA"
    if tma.is_file():
        lines = tma.read_text(encoding="utf-8", errors="ignore").splitlines()
        changed = 0
        rewritten: list[str] = []
        for line in lines:
            fields = line.split()
            if fields and fields[0].lstrip("+-").isdigit() and len(fields) >= 6:
                try:
                    if int(float(fields[4])) > cutoff:
                        fields[4] = str(cutoff)
                        fields[5] = "-99"
                        line = " ".join(fields)
                        changed += 1
                except ValueError:
                    pass
            rewritten.append(line)
        if changed:
            tma.write_text("\n".join(rewritten) + "\n", encoding="utf-8", newline="\n")
            corrections.append({"file": tma.name, "field": "HDAT/HWAM", "changed_rows": changed, "cutoff": cutoff})
    return corrections


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a versioned DSSAT experiment input bundle")
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--soil", required=True)
    parser.add_argument("--weather", required=True)
    parser.add_argument("--batch", required=True)
    parser.add_argument("--experiment", required=True, help="File stem, for example XXQL2501")
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument(
        "--observation-source-dir",
        default=None,
        help="Optional directory supplying FileA/FileT while FileX comes from --source-dir",
    )
    parser.add_argument("--site-lat", type=float, default=None)
    parser.add_argument("--site-lon", type=float, default=None)
    parser.add_argument("--out-root", default=str(PROJECT_ROOT / "data" / "user" / "experiments"))
    parser.add_argument("--derived-from-bundle", default=None)
    parser.add_argument(
        "--purpose",
        choices=("calibration", "sensitivity", "source"),
        default="calibration",
        help="Calibration requires FileA/FileT; sensitivity is simulation-only; source is actual-trial staging",
    )
    parser.add_argument(
        "--scenario-role",
        choices=("calibration", "validation"),
        default=None,
        help="Formal actual-trial role; validation bundles prohibit parameter calibration",
    )
    parser.add_argument(
        "--actual-trial-reference-filex",
        default=None,
        help="Reference FileX whose treatment-specific IC/SA/MI/MF must be preserved",
    )
    parser.add_argument(
        "--experiment-title",
        default=None,
        help="Optional corrected text after the FileX *EXP.DETAILS: label",
    )
    parser.add_argument(
        "--normalize-fertilizer-level",
        type=int,
        action="append",
        default=[],
        help="Make one FileX fertilizer factor level contiguous and chronological",
    )
    parser.add_argument(
        "--management-reference-filex",
        default=None,
        help="Reference FileX whose fertilizer/harvest sections are copied into the imported bundle",
    )
    parser.add_argument(
        "--symbi",
        choices=("Y", "N"),
        default=None,
        help="Audited FileX SYMBI option applied to every simulation-control level",
    )
    parser.add_argument(
        "--correction-note",
        action="append",
        default=[],
        help="Auditable description of a structural or metadata correction",
    )
    args = parser.parse_args()

    source = Path(args.source_dir).resolve()
    observation_source = Path(args.observation_source_dir).resolve() if args.observation_source_dir else source
    source_manifest_path = source / "input_manifest.json"
    source_manifest: dict[str, object] = {}
    if source_manifest_path.is_file():
        source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    destination = Path(args.out_root).resolve() / args.bundle_id
    if destination.exists():
        parser.error(f"Refusing to overwrite existing bundle: {destination}")
    destination.mkdir(parents=True)
    sources = [source / f"{args.experiment}.TMX"]
    observation_sources = [observation_source / f"{args.experiment}{suffix}" for suffix in (".TMA", ".TMT")]
    if args.purpose == "calibration":
        sources.extend(observation_sources)
    else:
        sources.extend(path for path in observation_sources if path.is_file())
    sources.extend([Path(args.soil).resolve(), Path(args.weather).resolve(), Path(args.batch).resolve()])
    for item in sources:
        if not item.is_file():
            parser.error(f"Required source missing: {item}")
        target_name = "DSSBatch.v48" if item == Path(args.batch).resolve() else item.name
        shutil.copy2(item, destination / target_name)

    metadata_corrections = []
    management_reference = None
    if args.management_reference_filex:
        management_reference = Path(args.management_reference_filex).resolve()
    elif args.experiment.upper() == "XXQL2501":
        default_management_reference = PROJECT_ROOT / "data" / "user" / "ref" / "XXQL2501.TMX"
        if default_management_reference.is_file():
            management_reference = default_management_reference
    if management_reference is not None:
        if not management_reference.is_file():
            parser.error(f"Management reference FileX missing: {management_reference}")
        filex_target = destination / f"{args.experiment}.TMX"
        replace_filex_management_sections(filex_target, management_reference)
        metadata_corrections.append(
            {
                "file": filex_target.name,
                "field": "fertilizer and harvest management sections",
                "value": "copied from authoritative reference",
                "reference_filex": str(management_reference),
                "reference_filex_sha256": sha256_file(management_reference),
                "scope": "*FERTILIZERS (INORGANIC) and *HARVEST DETAILS only",
                "authority": "corrected XXQL2501.TMX",
            }
        )
        harvest_dates = filex_harvest_dates(filex_target)
        if not harvest_dates:
            parser.error(f"Management reference has no harvest dates: {filex_target}")
        metadata_corrections.extend(
            _trim_estimated_harvest_observations(destination, args.experiment, max(harvest_dates))
        )
    if (args.site_lat is None) != (args.site_lon is None):
        parser.error("--site-lat and --site-lon must be provided together")
    if args.site_lat is not None and args.site_lon is not None:
        weather_target = destination / Path(args.weather).name
        _set_weather_coordinates(weather_target, args.site_lat, args.site_lon)
        metadata_corrections.append(
            {
                "file": weather_target.name,
                "field": "weather station latitude/longitude",
                "value": [args.site_lat, args.site_lon],
                "scope": "metadata only; daily weather series unchanged",
                "authority": "user decision in project thread",
            }
        )

    if args.symbi is not None:
        filex_target = destination / f"{args.experiment}.TMX"
        changed = _set_simulation_option(filex_target, "SYMBI", args.symbi)
        metadata_corrections.append(
            {
                "file": filex_target.name,
                "field": "simulation control SYMBI",
                "value": args.symbi,
                "scope": f"all {changed} FileX OPTIONS control row(s)",
                "authority": "user decision in project thread",
            }
        )

    if args.experiment_title is not None:
        filex_target = destination / f"{args.experiment}.TMX"
        _set_experiment_details(filex_target, args.experiment_title)
        metadata_corrections.append(
            {
                "file": filex_target.name,
                "field": "experiment details title",
                "value": args.experiment_title,
                "scope": "metadata only; management and observations unchanged",
                "authority": "user-provided season identity",
            }
        )

    if args.normalize_fertilizer_level:
        filex_target = destination / f"{args.experiment}.TMX"
        text = filex_target.read_text(encoding="utf-8", errors="ignore")
        for level in args.normalize_fertilizer_level:
            text = normalize_fertilizer_level_rows(text, level, "last")
        filex_target.write_text(text, encoding="utf-8", newline="\n")
        metadata_corrections.append(
            {
                "file": filex_target.name,
                "field": "fertilizer factor row order",
                "value": args.normalize_fertilizer_level,
                "scope": "row-order normalization only; all fertilizer values retained",
                "authority": "DSSAT input-order integrity gate",
            }
        )

    if management_reference is not None:
        alignment_findings = management_alignment_findings(
            destination / f"{args.experiment}.TMX", management_reference
        )
        if alignment_findings:
            raise ValueError("Imported FileX failed management-reference alignment")

    actual_trial_preservation = None
    if args.actual_trial_reference_filex is not None:
        if args.purpose != "calibration" or args.scenario_role is None:
            parser.error("--actual-trial-reference-filex requires calibration purpose and scenario role")
        reference_filex = Path(args.actual_trial_reference_filex).resolve()
        if not reference_filex.is_file():
            parser.error(f"Actual-trial reference FileX missing: {reference_filex}")
        actual_trial_preservation = _assert_actual_trial_preserved(
            destination / f"{args.experiment}.TMX", reference_filex
        )

    summary, findings = validate_input_bundle(
        destination,
        require_observations=args.purpose == "calibration",
    )
    files = []
    for item in sorted(path for path in destination.iterdir() if path.is_file()):
        files.append({"name": item.name, "sha256": sha256_file(item), "bytes": item.stat().st_size})
    authoritative_coordinates = (
        [args.site_lat, args.site_lon]
        if args.site_lat is not None
        else source_manifest.get("authoritative_coordinates")
    )
    manifest = {
        "bundle_id": args.bundle_id,
        "derived_from_bundle": args.derived_from_bundle,
        "derived_from_manifest_sha256": (
            sha256_file(source_manifest_path) if source_manifest_path.is_file() else None
        ),
        "correction_notes": args.correction_note,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_files": [str(path) for path in sources],
        "authoritative_coordinates": authoritative_coordinates,
        "metadata_corrections": metadata_corrections,
        "intended_use": (
            "independent_validation_against_observed_treatment_initial_conditions"
            if args.scenario_role == "validation"
            else "actual_trial_parameter_calibration"
            if args.scenario_role == "calibration"
            else "parameter_calibration_and_validation"
            if args.purpose == "calibration"
            else "actual_trial_source_candidate"
            if args.purpose == "source"
            else "sensitivity_analysis_only"
        ),
        "prohibited_use": ["parameter_calibration"] if args.scenario_role == "validation" else [],
        "scenario_type": "actual_trial_calibration" if args.scenario_role else None,
        "scenario_role": args.scenario_role,
        "observation_source_dir": str(observation_source),
        "treatment_plot_mapping": (
            "TN1-TN12 map one-to-one to plots 1-12; confirmed by user 2026-07-21"
            if args.scenario_role
            else None
        ),
        "initial_condition_policy": (
            "observed_treatment_specific_no_counterfactual_pooling" if actual_trial_preservation else None
        ),
        "soil_analysis_policy": (
            "observed_treatment_specific_no_counterfactual_pooling" if actual_trial_preservation else None
        ),
        "counterfactual_transformations": [] if actual_trial_preservation else None,
        "actual_trial_preservation": actual_trial_preservation,
        "management_reference_filex": str(management_reference) if management_reference else None,
        "management_reference_filex_sha256": (
            sha256_file(management_reference) if management_reference else None
        ),
        "observation_policy": (
            "FileA_and_FileT_required"
            if args.purpose == "calibration"
            else "FileA_and_FileT_optional_actual_trial_source"
            if args.purpose == "source"
            else "simulation_only_FileA_and_FileT_optional"
        ),
        "files": files,
        "summary": summary,
        "findings": findings_as_dicts(findings),
        "science_status": "fail" if any(item.severity == "error" for item in findings) else "pass_with_warnings" if findings else "pass",
    }
    (destination / "input_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"bundle": str(destination), "science_status": manifest["science_status"], "findings": manifest["findings"]}, ensure_ascii=False, indent=2))
    return 2 if manifest["science_status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
