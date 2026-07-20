"""Build counterfactual FileX bundles and replay failed Morris candidates.

The source input bundle is never modified. Counterfactual variants are written
under a diagnostic output directory and are not valid scientific observations.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.common.experiment_inputs import batch_entries, parse_filex
from src.sensitivity.replay_morris_failure import read_flat_manifest, replay_candidates


INITIAL_COMPONENT_INDEX = {"sh2o": 2, "snh4": 3, "sno3": 4}


def _replace_tokens(line: str, replacements: dict[int, str]) -> str:
    spans: list[tuple[int, int]] = []
    in_token = False
    start = 0
    for index, char in enumerate(line + " "):
        if not char.isspace() and not in_token:
            start = index
            in_token = True
        elif char.isspace() and in_token:
            spans.append((start, index))
            in_token = False
    updated = line
    for token_index, value in sorted(replacements.items(), reverse=True):
        start, end = spans[token_index]
        replacement = str(value)
        width = end - start
        if len(replacement) <= width:
            replacement = replacement.rjust(width)
        updated = updated[:start] + replacement + updated[end:]
    return updated


def replace_treatment_factors(text: str, treatment: int, updates: dict[str, int]) -> str:
    """Return FileX text with selected factor-level references replaced."""

    lines = text.splitlines()
    in_treatments = False
    factor_names: list[str] = []
    found = False
    for index, line in enumerate(lines):
        upper = line.strip().upper()
        if upper.startswith("*TREATMENTS"):
            in_treatments = True
            continue
        if in_treatments and line.startswith("*"):
            break
        if not in_treatments:
            continue
        if upper.startswith("@"):
            factor_names = upper.lstrip("@").split()[-13:]
            continue
        tokens = line.split()
        if not tokens or not factor_names:
            continue
        try:
            row_treatment = int(tokens[0])
        except ValueError:
            continue
        if row_treatment != int(treatment):
            continue
        replacements: dict[int, str] = {}
        factor_offset = len(tokens) - len(factor_names)
        for name, value in updates.items():
            key = name.upper()
            if key not in factor_names:
                raise KeyError(f"Factor {name} is absent from FileX treatment header")
            replacements[factor_offset + factor_names.index(key)] = str(int(value))
        lines[index] = _replace_tokens(line, replacements)
        found = True
        break
    if not found:
        raise KeyError(f"Treatment {treatment} was not found in FileX")
    return "\n".join(lines) + "\n"


def replace_initial_components(
    text: str,
    target_ic: int,
    reference_ic: int,
    components: tuple[str, ...],
) -> str:
    """Copy selected layer values from one initial-condition profile to another."""

    invalid = set(components) - set(INITIAL_COMPONENT_INDEX)
    if invalid:
        raise KeyError(f"Unsupported initial-condition components: {sorted(invalid)}")
    parsed = parse_filex_text(text)
    reference = {
        float(row["depth"]): row for row in parsed["initial_conditions"].get(int(reference_ic), [])
    }
    target = parsed["initial_conditions"].get(int(target_ic), [])
    if not reference or not target:
        raise KeyError(f"IC{target_ic} or IC{reference_ic} is absent from FileX")
    missing_depths = sorted({float(row["depth"]) for row in target} - set(reference))
    if missing_depths:
        raise ValueError(f"Reference IC lacks target depths: {missing_depths}")

    lines = text.splitlines()
    in_initial = False
    layer_header = False
    changed = 0
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
        source = reference[depth]
        replacements = {
            INITIAL_COMPONENT_INDEX[name]: format(float(source[name]), "g") for name in components
        }
        lines[index] = _replace_tokens(line, replacements)
        changed += 1
    if changed != len(target):
        raise ValueError(f"Expected {len(target)} IC layers but changed {changed}")
    return "\n".join(lines) + "\n"


def fertilizer_n_dates(text: str, fertilizer_level: int) -> list[int]:
    """Return ordered dates containing positive mineral-N applications for an MF level."""

    dates: list[int] = []
    in_fertilizers = False
    header: list[str] = []
    for line in text.splitlines():
        upper = line.strip().upper()
        if upper.startswith("*FERTILIZERS (INORGANIC)"):
            in_fertilizers = True
            continue
        if in_fertilizers and line.startswith("*"):
            break
        if not in_fertilizers:
            continue
        if upper.startswith("@F"):
            header = upper.lstrip("@").split()
            continue
        tokens = line.split()
        if not header or len(tokens) < len(header):
            continue
        try:
            level = int(tokens[0])
            date = int(tokens[header.index("FDATE")])
            nitrogen = float(tokens[header.index("FAMN")])
        except (ValueError, IndexError):
            continue
        if level == int(fertilizer_level) and nitrogen > 0 and date not in dates:
            dates.append(date)
    return dates


def fertilizer_n_total_kg_ha(text: str, fertilizer_level: int) -> float:
    """Total mineral nitrogen (kg N/ha) applied under one FileX fertilizer factor level.

    Sums the ``FAMN`` column across every event row of the requested MF level in
    the ``*FERTILIZERS (INORGANIC)`` section. The value is the actual seasonal
    dose — it is NOT rounded, clamped, or matched to a nominal N-level ladder.
    Per-season FileX schedules differ (XXQL2501 MF1=399, XXQL2502/XXQL2601
    MF1=360/361 kg N/ha), so the sensitivity output contract must read the
    derived dose rather than a hardcoded constant.

    Raises ``ValueError`` if the FERTILIZERS section or the FAMN column is
    absent, or if no rows match the requested level.
    """

    in_fertilizers = False
    header: list[str] = []
    matched_rows = 0
    total = 0.0
    for line in text.splitlines():
        upper = line.strip().upper()
        if upper.startswith("*FERTILIZERS (INORGANIC)"):
            in_fertilizers = True
            continue
        if in_fertilizers and line.startswith("*"):
            break
        if not in_fertilizers:
            continue
        if upper.startswith("@F"):
            header = upper.lstrip("@").split()
            if "FAMN" not in header:
                raise ValueError("FileX FERTILIZERS header lacks the FAMN column")
            continue
        tokens = line.split()
        if not header or len(tokens) < len(header):
            continue
        try:
            level = int(tokens[0])
            nitrogen = float(tokens[header.index("FAMN")])
        except (ValueError, IndexError):
            continue
        if level == int(fertilizer_level):
            total += nitrogen
            matched_rows += 1
    if matched_rows == 0:
        raise ValueError(
            f"No FERTILIZERS rows matched MF level {fertilizer_level}; "
            "check that the level exists in the FileX"
        )
    return float(total)


def replace_fertilizer_n(
    text: str,
    target_mf: int,
    reference_mf: int,
    dates: set[int] | None = None,
) -> str:
    """Copy FAMN values from a reference MF schedule into selected target dates."""

    lines = text.splitlines()
    in_fertilizers = False
    header: list[str] = []
    reference: dict[tuple[int, str, str], str] = {}
    rows: list[tuple[int, int, tuple[int, str, str]]] = []
    for index, line in enumerate(lines):
        upper = line.strip().upper()
        if upper.startswith("*FERTILIZERS (INORGANIC)"):
            in_fertilizers = True
            continue
        if in_fertilizers and line.startswith("*"):
            break
        if not in_fertilizers:
            continue
        if upper.startswith("@F"):
            header = upper.lstrip("@").split()
            continue
        tokens = line.split()
        if not header or len(tokens) < len(header):
            continue
        try:
            level = int(tokens[0])
            date = int(tokens[header.index("FDATE")])
            key = (date, tokens[header.index("FMCD")], tokens[header.index("FACD")])
            famn = tokens[header.index("FAMN")]
        except (ValueError, IndexError):
            continue
        if level == int(reference_mf):
            reference[key] = famn
        elif level == int(target_mf):
            rows.append((index, date, key))

    changed = 0
    famn_index = header.index("FAMN")
    for index, date, key in rows:
        if dates is not None and date not in dates:
            continue
        if key not in reference:
            raise ValueError(f"Reference MF{reference_mf} lacks fertilizer row {key}")
        lines[index] = _replace_tokens(lines[index], {famn_index: reference[key]})
        changed += 1
    if changed == 0:
        raise ValueError("No fertilizer nitrogen rows were changed")
    return "\n".join(lines) + "\n"


def normalize_fertilizer_level_rows(text: str, fertilizer_level: int, placement: str) -> str:
    """Make one MF level contiguous and chronological without changing row values."""

    if placement not in {"first", "last"}:
        raise ValueError("placement must be 'first' or 'last'")
    lines = text.splitlines()
    section_start = next(
        (i for i, line in enumerate(lines) if line.strip().upper().startswith("*FERTILIZERS (INORGANIC)")),
        None,
    )
    if section_start is None:
        raise ValueError("FileX lacks an inorganic-fertilizer section")
    section_end = next(
        (i for i in range(section_start + 1, len(lines)) if lines[i].startswith("*")),
        len(lines),
    )
    selected: list[tuple[int, int, str]] = []
    selected_indexes: set[int] = set()
    for index in range(section_start + 1, section_end):
        tokens = lines[index].split()
        if not tokens:
            continue
        try:
            level = int(tokens[0])
            date = int(tokens[1])
        except (ValueError, IndexError):
            continue
        if level == int(fertilizer_level):
            selected.append((date, index, lines[index]))
            selected_indexes.add(index)
    if not selected:
        raise KeyError(f"MF{fertilizer_level} has no fertilizer rows")
    ordered = [line for _, _, line in sorted(selected, key=lambda item: (item[0], item[1]))]
    remaining = [line for index, line in enumerate(lines) if index not in selected_indexes]
    if placement == "first":
        original_first = min(selected_indexes)
        insertion = sum(1 for index in range(original_first) if index not in selected_indexes)
    else:
        original_end = section_end
        insertion = sum(1 for index in range(original_end) if index not in selected_indexes)
    remaining[insertion:insertion] = ordered
    return "\n".join(remaining) + "\n"


def parse_filex_text(text: str) -> dict[str, Any]:
    """Parse FileX text without altering the authoritative source file."""

    # This local parser covers only the initial-condition table needed here.
    initial: dict[int, list[dict[str, float]]] = {}
    lines = text.splitlines()
    in_initial = False
    layer_header = False
    for line in lines:
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
            ic = int(tokens[0])
            initial.setdefault(ic, []).append(
                {
                    "depth": float(tokens[1]),
                    "sh2o": float(tokens[2]),
                    "snh4": float(tokens[3]),
                    "sno3": float(tokens[4]),
                }
            )
        except ValueError:
            continue
    return {"initial_conditions": initial}


def variant_definitions(target: dict[str, int], reference: dict[str, int]) -> dict[str, dict[str, Any]]:
    """Define the minimum IC/MF factorial plus IC water/nitrogen decomposition."""

    return {
        f"baseline_ic{target['IC']}_mf{target['MF']}": {},
        f"factor_ic{reference['IC']}_mf{target['MF']}": {"factors": {"IC": reference["IC"]}},
        f"factor_ic{target['IC']}_mf{reference['MF']}": {"factors": {"MF": reference["MF"]}},
        f"factor_ic{reference['IC']}_mf{reference['MF']}": {
            "factors": {"IC": reference["IC"], "MF": reference["MF"]}
        },
        f"ic{target['IC']}_sh2o_from_ic{reference['IC']}": {"components": ("sh2o",)},
        f"ic{target['IC']}_n_from_ic{reference['IC']}": {"components": ("snh4", "sno3")},
        f"ic{target['IC']}_snh4_from_ic{reference['IC']}": {"components": ("snh4",)},
        f"ic{target['IC']}_sno3_from_ic{reference['IC']}": {"components": ("sno3",)},
        f"ic{target['IC']}_all_from_ic{reference['IC']}": {
            "components": ("sh2o", "snh4", "sno3")
        },
    }


def fertilizer_variant_definitions(
    text: str, target_mf: int, reference_mf: int
) -> dict[str, dict[str, Any]]:
    dates = fertilizer_n_dates(text, target_mf)
    if len(dates) < 3:
        raise ValueError(f"MF{target_mf} needs at least three N application dates for temporal attribution")
    basal = {dates[0]}
    topdress = dates[1:]
    split = (len(topdress) + 1) // 2
    early = set(topdress[:split])
    late = set(topdress[split:])
    last = {dates[-1]}
    return {
        f"baseline_mf{target_mf}": {},
        f"mf{target_mf}_all_n_from_mf{reference_mf}": {"fertilizer_dates": set(dates)},
        f"mf{target_mf}_basal_n_from_mf{reference_mf}": {"fertilizer_dates": basal},
        f"mf{target_mf}_topdress_n_from_mf{reference_mf}": {"fertilizer_dates": set(topdress)},
        f"mf{target_mf}_early_topdress_from_mf{reference_mf}": {"fertilizer_dates": early},
        f"mf{target_mf}_late_topdress_from_mf{reference_mf}": {"fertilizer_dates": late},
        f"mf{target_mf}_last_n_from_mf{reference_mf}": {"fertilizer_dates": last},
        f"mf{target_mf}_except_last_from_mf{reference_mf}": {
            "fertilizer_dates": set(dates) - last
        },
    }


def structure_variant_definitions(target: dict[str, int], reference: dict[str, int]) -> dict[str, dict[str, Any]]:
    return {
        f"mf{reference['MF']}_normalized_first": {
            "normalize_mf": (reference["MF"], "first"),
        },
        f"mf{reference['MF']}_normalized_last": {
            "normalize_mf": (reference["MF"], "last"),
        },
        f"factor_mf{reference['MF']}_original_order": {"factors": {"MF": reference["MF"]}},
        f"factor_mf{reference['MF']}_normalized_first": {
            "factors": {"MF": reference["MF"]},
            "normalize_mf": (reference["MF"], "first"),
        },
        f"factor_mf{reference['MF']}_normalized_last": {
            "factors": {"MF": reference["MF"]},
            "normalize_mf": (reference["MF"], "last"),
        },
        f"factor_mf{target['MF']}_normalized_first": {
            "normalize_mf": (target["MF"], "first"),
        },
        f"factor_mf{target['MF']}_normalized_last": {
            "normalize_mf": (target["MF"], "last"),
        },
    }


def build_variants(
    source_input_dir: str | Path,
    destination: str | Path,
    *,
    target_treatment: int,
    reference_treatment: int,
    variant_set: str = "ic-mf",
) -> dict[str, Path]:
    source = Path(source_input_dir).resolve()
    entries = batch_entries(source / "DSSBatch.v48")
    if not entries:
        raise ValueError("Input bundle batch contains no FileX treatments")
    filex_name = entries[0][0]
    parsed = parse_filex(source / filex_name)
    treatments = parsed["treatments"]
    target = treatments[int(target_treatment)]
    reference = treatments[int(reference_treatment)]
    if target.get("MI") != reference.get("MI"):
        raise ValueError("Target and reference treatments must share MI for IC/MF attribution")

    output_root = Path(destination).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    source_text = (source / filex_name).read_text(encoding="utf-8", errors="ignore")
    if variant_set == "ic-mf":
        definitions = variant_definitions(target, reference)
    elif variant_set == "fertilizer":
        definitions = fertilizer_variant_definitions(source_text, target["MF"], reference["MF"])
    elif variant_set == "structure":
        definitions = structure_variant_definitions(target, reference)
    else:
        raise ValueError(f"Unsupported variant set: {variant_set}")

    created: dict[str, Path] = {}
    for name, spec in definitions.items():
        bundle = output_root / name
        if bundle.exists():
            raise FileExistsError(f"Diagnostic variant already exists: {bundle}")
        shutil.copytree(source, bundle)
        filex = bundle / filex_name
        text = filex.read_text(encoding="utf-8", errors="ignore")
        if spec.get("factors"):
            text = replace_treatment_factors(text, target_treatment, spec["factors"])
        if spec.get("components"):
            text = replace_initial_components(
                text,
                target["IC"],
                reference["IC"],
                spec["components"],
            )
        if spec.get("fertilizer_dates"):
            text = replace_fertilizer_n(
                text,
                target["MF"],
                reference["MF"],
                spec["fertilizer_dates"],
            )
        if spec.get("normalize_mf"):
            level, placement = spec["normalize_mf"]
            text = normalize_fertilizer_level_rows(text, level, placement)
        filex.write_text(text, encoding="utf-8")
        created[name] = bundle
    return created


def run_attribution(
    case_dir: str | Path,
    run_ids: list[int],
    out_dir: str | Path,
    *,
    target_treatment: int,
    reference_treatment: int,
    execute: bool,
    variant_set: str = "ic-mf",
) -> dict[str, Any]:
    case_root = Path(case_dir).resolve()
    manifest = read_flat_manifest(case_root / "run_manifest.yaml")
    source_input = Path(manifest.get("input_dir", "")).resolve()
    output = Path(out_dir).resolve()
    variants = build_variants(
        source_input,
        output / "input_variants",
        target_treatment=target_treatment,
        reference_treatment=reference_treatment,
        variant_set=variant_set,
    )
    records: list[dict[str, Any]] = []
    for name, bundle in variants.items():
        results = replay_candidates(
            case_root,
            run_ids,
            out_dir=output / "replays" / name,
            treatments=[target_treatment],
            execute=execute,
            input_dir_override=bundle,
        )
        for item in results:
            records.append({"variant": name, **item})

    summary: list[dict[str, Any]] = []
    for name in variants:
        selected = [row for row in records if row["variant"] == name]
        summary.append(
            {
                "variant": name,
                "runs": len(selected),
                "success": sum(row["status"] == "success" for row in selected),
                "model_failed": sum(row["status"] == "model_failed" for row in selected),
                "prepared": sum(row["status"] == "prepared" for row in selected),
            }
        )

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "case_dir": str(case_root),
        "source_input_dir": str(source_input),
        "target_treatment": int(target_treatment),
        "reference_treatment": int(reference_treatment),
        "variant_set": variant_set,
        "run_ids": [int(value) for value in run_ids],
        "execute": bool(execute),
        "summary": summary,
        "records": records,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "attribution_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (output / "attribution_summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["variant", "runs", "success", "model_failed", "prepared"])
        writer.writeheader()
        writer.writerows(summary)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Counterfactual DSSAT treatment-factor attribution")
    parser.add_argument("--case-dir", required=True)
    parser.add_argument("--run-id", type=int, action="append", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--target-treatment", type=int, default=2)
    parser.add_argument("--reference-treatment", type=int, default=3)
    parser.add_argument(
        "--variant-set",
        choices=("ic-mf", "fertilizer", "structure"),
        default="ic-mf",
    )
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    report = run_attribution(
        args.case_dir,
        args.run_id,
        args.out_dir,
        target_treatment=args.target_treatment,
        reference_treatment=args.reference_treatment,
        execute=args.execute,
        variant_set=args.variant_set,
    )
    for row in report["summary"]:
        print(
            f"{row['variant']}: runs={row['runs']} success={row['success']} "
            f"model_failed={row['model_failed']} prepared={row['prepared']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
