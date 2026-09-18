"""Prepare the generated soil-N calibration bundle without mutating raw inputs.

The user-specified FileX files are authoritative for SANI/SNH4/SNO3.  Their
SH2O rows are replaced only in the generated calibration copies with the
project's audited valid-layer-mean SH2O rows, because several source rows are
above the SOIL.SOL saturation limit and DSSAT rejects them as IPSLIN.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dssat.run_dssat import update_initial_soil_n_file


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def update_manifest(path: Path, *, source_file: Path) -> None:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    filex_name = source_file.name
    filex_hash = sha256(path.parent / filex_name)
    filex_bytes = (path.parent / filex_name).stat().st_size
    for record in manifest.get("files", []):
        if record.get("name") == filex_name:
            record["sha256"] = filex_hash
            record["bytes"] = filex_bytes
    for records in manifest.get("files_by_role", {}).values():
        if not isinstance(records, list):
            continue
        for record in records:
            if record.get("name") == filex_name:
                record["sha256"] = filex_hash
                record["bytes"] = filex_bytes
                record["copied_from"] = str(source_file)
                record["copied_from_note"] = (
                    "SH2O-only valid-layer-mean reference; SANI/SNH4/SNO3 "
                    "calibration anchors remain from the user-specified FileX."
                )
    manifest["filex_fix_status"] = (
        "SH2O replaced in generated calibration copy by audited valid-layer "
        "means; user-specified SANI/SNH4/SNO3 remain the calibration anchors."
    )
    manifest.setdefault("calibration_notes", []).append(
        "Runtime input copy uses valid-layer-mean SH2O only to avoid DSSAT IPSLIN; "
        "raw user FileX is not modified."
    )
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--normalize-with-param-csv",
        type=Path,
        default=None,
        help=(
            "Optional generated parameter CSV used to rewrite each copied "
            "FileX initial-N block with explicit whitespace-delimited fields."
        ),
    )
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    normalize_params = (
        args.normalize_with_param_csv.expanduser().resolve()
        if args.normalize_with_param_csv
        else None
    )
    if normalize_params is not None and not normalize_params.is_file():
        raise FileNotFoundError(f"normalization parameter CSV not found: {normalize_params}")
    mappings = {
        "25SP": ("XXQL2501", "xxql2501_layermean_ic_valid_n012_v1_20260801", None),
        "25FA": ("XXQL2502", "xxql2502_layermean_ic_valid_n012_v1_20260801", None),
        "26SP": ("XXQL2601", "xxql2601_layermean_ic_valid_n012_v1_20260801", None),
    }
    for season, bundle_name in mappings.items():
        target_dir = run_dir / "inputs" / season
        excode, water_bundle, section_reference = bundle_name
        user_file = ROOT / "data" / "user" / "experiments" / excode / f"{excode}.TMX"
        water_manifest = ROOT / "data" / "user" / "experiments" / water_bundle / "input_manifest.json"
        water_file = ROOT / "data" / "user" / "experiments" / water_bundle / f"{excode}.TMX"
        target = target_dir / f"{excode}.TMX"
        if not user_file.is_file() or not water_file.is_file() or not target.is_file() or not water_manifest.is_file():
            raise FileNotFoundError(f"missing FileX/reference manifest: {user_file} / {water_manifest}")
        # The model copy uses the audited DSSAT-valid initial-condition section.
        # The builder reads user_file separately for N bounds, and the runner
        # injects those treatment/layer-specific values into this copy.
        shutil.copy2(water_file if section_reference is None else user_file, target)
        # Some DSSAT builds interpret the blank separator immediately before
        # *PLANTING DETAILS as an extra initial-condition row (IPSLIN).  Remove
        # it in the generated calibration copy only; raw user inputs remain
        # untouched.
        target_lines = target.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
        cleaned_lines = []
        in_initial = False
        for index, line in enumerate(target_lines):
            stripped = line.strip().upper()
            if stripped.startswith("*INITIAL CONDITIONS"):
                in_initial = True
            if in_initial and not stripped:
                next_nonempty = next((x.strip().upper() for x in target_lines[index + 1 :] if x.strip()), "")
                if next_nonempty.startswith("*PLANTING DETAILS"):
                    continue
            if in_initial and stripped.startswith("*") and not stripped.startswith("*INITIAL CONDITIONS"):
                in_initial = False
            cleaned_lines.append(line)
        target.write_text("".join(cleaned_lines), encoding="utf-8")
        if section_reference is not None:
            target_lines = target.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
            reference_lines = section_reference.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
            def section_bounds(lines):
                start = next(i for i, line in enumerate(lines) if line.strip().upper().startswith("*INITIAL CONDITIONS"))
                end = next(i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("*"))
                return start, end
            start, end = section_bounds(target_lines)
            ref_start, ref_end = section_bounds(reference_lines)
            merged = target_lines[:start] + reference_lines[ref_start:ref_end] + target_lines[end:]
            cleaned = []
            for index, line in enumerate(merged):
                if not line.strip():
                    next_section = ""
                    for candidate in merged[index + 1 :]:
                        if candidate.strip():
                            next_section = candidate.strip().upper()
                            break
                    if next_section.startswith("*PLANTING DETAILS"):
                        continue
                cleaned.append(line)
            target.write_text("".join(cleaned), encoding="utf-8")
            water_file = section_reference
        if normalize_params is not None:
            # This only touches the generated bundle copy.  It makes the
            # fixed-width legacy IC rows unambiguous before PEST++ candidates
            # are injected; raw user FileX files remain read-only.
            update_initial_soil_n_file(
                param_csv_path=str(normalize_params),
                filex_path=str(target),
            )
        update_manifest(target_dir / "input_manifest.json", source_file=water_file)
        manifest = json.loads((target_dir / "input_manifest.json").read_text(encoding="utf-8"))
        manifest.setdefault("calibration_notes", []).append(
            f"Initial SANI/SNH4/SNO3 bounds read from user FileX: {user_file}."
        )
        (target_dir / "input_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    design_path = run_dir / "soil_n_design.json"
    design = json.loads(design_path.read_text(encoding="utf-8"))
    for season in design.get("seasons", []):
        # A copied retry directory must use its own localized bundle, not the
        # absolute bundle path inherited from the source run.  Otherwise a
        # previous retry's injected/normalized FileX silently becomes the
        # source for the new calibration.
        local_bundle = run_dir / "inputs" / str(season["season_id"])
        if not local_bundle.is_dir():
            raise FileNotFoundError(f"missing localized bundle for {season['season_id']}: {local_bundle}")
        season["bundle_path"] = str(local_bundle)
        manifest_path = Path(season["bundle_path"]) / "input_manifest.json"
        season["bundle_manifest_sha256"] = sha256(manifest_path)
        season["initial_soil_n_reference_filex"] = str(
            ROOT / "data" / "user" / "experiments" / season["experiment_code"] / f"{season['experiment_code']}.TMX"
        )
    design["initial_condition_policy"] = (
        "User-specified FileX SANI/SNH4/SNO3 anchors; valid-layer-mean SH2O in "
        "generated copy only to satisfy DSSAT physical input checks; IC rows "
        "are whitespace-normalized before candidate injection."
    )
    design_path.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
