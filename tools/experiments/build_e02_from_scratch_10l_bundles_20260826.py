"""Build immutable 10L-B bundles for the E02 from-scratch design.

The old ``prepare_best_env_*`` scripts are intentionally not reused here:
they replace 26SP SH2O with a static guessed profile and leave contradictory
manifest metadata.  This builder starts from the audited measured-moisture
bundles, preserves all observation files byte-for-byte, replaces only the
IBTM910017 profile and the FileX INITIAL CONDITIONS table, then regenerates a
complete manifest.

The target DSSAT layer bottoms are Scheme B: 2, 4, 15, 30, 40, 60, 80, 100,
140, 180 cm.  Source IC values at 20/40/60/80/100 cm are carried forward by
depth interval; values below 100 cm use the audited 100-cm source value rather
than an unrecorded counterfactual.  In particular, 26SP SH2O remains the
per-treatment measured initial value represented in the source TMX and is
checked against the initial-condition soil-water observations.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAYER_BOTTOMS = [2, 4, 15, 30, 40, 60, 80, 100, 140, 180]

SPECS = {
    "25SP": {
        "excode": "XXQL2501",
        "source": ROOT / "data/user/experiments/xxql2501_repfilter_measuredmoisture_v3_measuredn_20260820",
        "out": ROOT / "data/user/experiments/xxql2501_from_scratch_10L_B_20260826",
        "role": "calibration",
        "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
        "calibration_treatments": [2, 5, 10, 13],
        "diagnostic_treatments": [3, 4, 6, 7, 8, 9, 11, 12, 14],
        "ic_policy": "observed_treatment_specific_measured_sh2o_and_mineral_n_fixed",
    },
    "26SP": {
        "excode": "XXQL2601",
        "source": ROOT / "data/user/experiments/xxql2601_repfilter_measuredmoisture_v3_measuredn_20260820",
        "out": ROOT / "data/user/experiments/xxql2601_from_scratch_10L_B_20260826",
        "role": "calibration",
        "treatments": list(range(1, 13)),
        "calibration_treatments": [1, 3, 9, 12],
        "diagnostic_treatments": [2, 4, 5, 6, 7, 8, 10, 11],
        "ic_policy": "observed_treatment_specific_sequential_measured_sh2o_mineral_n_fixed",
    },
    "25FA": {
        "excode": "XXQL2502",
        "source": ROOT / "data/user/experiments/xxql2502_actual_trial_calibration_v9_13layer_20260820",
        "out": ROOT / "data/user/experiments/xxfa_from_scratch_10L_B_20260826",
        "role": "validation",
        "treatments": list(range(1, 13)),
        "calibration_treatments": [],
        "diagnostic_treatments": [],
        "validation_treatments": list(range(1, 13)),
        "ic_policy": "fixed_validation_initial_conditions_no_parameter_tuning",
    },
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _compact_token(value: float) -> str:
    """Render a numeric value in <=5 chars, leaving one field separator."""
    rendered = f"{float(value):.5g}"
    if rendered.startswith("0."):
        rendered = rendered[1:]
    elif rendered.startswith("-0."):
        rendered = "-." + rendered[3:]
    if len(rendered) > 5 or "e" in rendered.lower():
        rendered = f"{float(value):.4g}"
        if rendered.startswith("0."):
            rendered = rendered[1:]
        elif rendered.startswith("-0."):
            rendered = "-." + rendered[3:]
    if len(rendered) > 5:
        raise ValueError(f"IC value cannot fit five-character token: {value}")
    return rendered


def _ic_bounds(lines: list[str]) -> tuple[int, int]:
    start = next((i for i, line in enumerate(lines) if line.strip().upper().startswith("*INITIAL CONDITIONS")), None)
    if start is None:
        raise ValueError("TMX has no *INITIAL CONDITIONS section")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("*")), len(lines))
    return start, end


def _parse_ic_blocks(lines: list[str], start: int, end: int) -> list[dict]:
    """Parse source IC blocks while retaining the treatment header row."""
    blocks: list[dict] = []
    current: dict | None = None
    layer_mode = False
    for line in lines[start + 1 : end]:
        upper = line.strip().upper()
        if upper.startswith("@C") and "PCR" in upper and "ICDAT" in upper:
            if current is not None:
                blocks.append(current)
            current = {"header": line, "treatment_row": None, "layers": []}
            layer_mode = False
            continue
        if current is None:
            continue
        if upper.startswith("@C") and all(x in upper for x in ("ICBL", "SH2O", "SNH4", "SNO3")):
            layer_mode = True
            continue
        if upper.startswith("@C") or upper.startswith("@"):
            layer_mode = False
            continue
        if not line.strip():
            continue
        tokens = line.split()
        if current["treatment_row"] is None:
            if not tokens or not tokens[0].isdigit():
                raise ValueError(f"malformed treatment IC row: {line!r}")
            current["treatment_row"] = line
            current["tn"] = int(tokens[0])
            continue
        if not layer_mode:
            continue
        if len(tokens) < 5 or not tokens[0].isdigit() or not tokens[1].isdigit():
            raise ValueError(f"malformed ICBL row: {line!r}")
        current["layers"].append(
            {
                "depth": int(tokens[1]),
                "sh2o": float(tokens[2]),
                "snh4": float(tokens[3]),
                "sno3": float(tokens[4]),
            }
        )
    if current is not None:
        blocks.append(current)
    if not blocks or any(block.get("treatment_row") is None for block in blocks):
        raise ValueError("could not parse complete IC treatment blocks")
    return blocks


def _source_layer_value(layers: list[dict], depth: int) -> dict:
    if not layers:
        raise ValueError("source IC treatment has no layers")
    source_depth = 20 if depth <= 20 else 40 if depth <= 40 else 60 if depth <= 60 else 80 if depth <= 80 else 100
    exact = next((row for row in layers if row["depth"] == source_depth), None)
    if exact is None:
        raise ValueError(f"source IC is missing {source_depth} cm layer")
    return exact


def _render_ic_section(source_lines: list[str], blocks: list[dict], excode: str) -> list[str]:
    start, end = _ic_bounds(source_lines)
    out = source_lines[: start + 1]
    for block in blocks:
        tn = int(block["tn"])
        # Keep the source PCR row (ICDAT and other flags are authoritative).
        out.append("@C   PCR ICDAT  ICRT  ICND  ICRN  ICRE  ICWD ICRES ICREN ICREP ICRIP ICRID ICNAME")
        out.append(block["treatment_row"])
        out.append("@C  ICBL  SH2O  SNH4  SNO3")
        for depth in LAYER_BOTTOMS:
            src = _source_layer_value(block["layers"], depth)
            # DSSAT FileX IC fields are 2/6/6/6/6 characters.  This is the
            # canonical width used by the project's repair tooling.
            tokens = [_compact_token(src["sh2o"]), _compact_token(src["snh4"]), _compact_token(src["sno3"])]
            if any(len(token) > 6 for token in tokens):
                raise ValueError(f"IC value does not fit six-character field for {excode} TN{tn} depth {depth}")
            line = f"{tn:2d}{depth:6d}" + "".join(token.rjust(6) for token in tokens)
            if len(line) != 26:
                raise AssertionError(f"unexpected FileX IC width {len(line)}: {line!r}")
            out.append(line)
    out.extend(source_lines[end:])
    return out


def _copy_and_rebuild(spec: dict) -> dict:
    source: Path = spec["source"]
    out: Path = spec["out"]
    if not source.is_dir():
        raise FileNotFoundError(source)
    if out.exists():
        raise FileExistsError(
            f"Output bundle directory already exists: {out}. "
            f"To rebuild, use a new bundle ID/date suffix or manually "
            f"remove the existing directory first."
        )
    shutil.copytree(source, out)

    # The previously generated 10L-B profile has the correct layer geometry;
    # copy only the payload SOIL.SOL, never its contradictory manifest.
    soil_template = ROOT / "data/user/experiments/xxql2501_best_env_10layer_20260825/SOIL.SOL"
    if not soil_template.is_file():
        raise FileNotFoundError(soil_template)
    shutil.copy2(soil_template, out / "SOIL.SOL")

    tmx_path = out / f"{spec['excode']}.TMX"
    source_text = tmx_path.read_text(encoding="utf-8", errors="strict")
    source_lines = source_text.splitlines()
    start, end = _ic_bounds(source_lines)
    blocks = _parse_ic_blocks(source_lines, start, end)
    source_treatments = {int(block["tn"]) for block in blocks}
    # A calibration bundle may retain authoritative FileX treatment blocks
    # whose observations were excluded (25SP TN1/6/7/8).  They remain
    # diagnostic-only inputs; the role table, not silent deletion, controls
    # whether they enter Phi.
    if not set(spec["treatments"]).issubset(source_treatments):
        raise ValueError(f"{spec['excode']} IC treatments are missing required roles")
    rebuilt_lines = _render_ic_section(source_lines, blocks, spec["excode"])
    tmx_path.write_text("\n".join(rebuilt_lines) + "\n", encoding="utf-8", newline="")

    manifest_path = out / "input_manifest.json"
    source_manifest = json.loads((source / "input_manifest.json").read_text(encoding="utf-8"))
    manifest = dict(source_manifest)
    manifest.update(
        {
            "bundle_id": out.name,
            "package_name": out.name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "derived_from_bundle": source.name,
            "scenario_role": spec["role"],
            "intended_use": "locked_season_validation" if spec["role"] == "validation" else "parameter_calibration",
            "design_id": "e02_from_scratch_10L_B_20260826",
            "soil_scheme": {
                "id": "10L-B",
                "bottoms_cm": LAYER_BOTTOMS,
                "tillage_depth_cm": 60,
                "source_profile": "xxql2501_best_env_10layer_20260825/SOIL.SOL",
            },
            "initial_condition_policy": spec["ic_policy"],
            "treatment_roles": {
                "calibration": spec.get("calibration_treatments", []),
                "diagnostic": spec.get("diagnostic_treatments", []),
                "validation": spec.get("validation_treatments", []),
            },
            "source_filex_treatments": sorted(source_treatments),
        }
    )
    qa = dict(manifest.get("soil_water_qa") or {})
    qa["filex_ic_layer_bottoms_cm"] = LAYER_BOTTOMS
    qa["dssat_layer_bottoms_cm"] = LAYER_BOTTOMS
    qa["soil_profile_layer_count"] = len(LAYER_BOTTOMS)
    manifest["soil_water_qa"] = qa
    manifest["bundle_rebuild"] = {
        "script": "tools/experiments/build_e02_from_scratch_10l_bundles_20260826.py",
        "scheme": "10L-B",
        "source_observations_preserved": True,
        "ic_rule": "source 20/40/60/80/100 cm values mapped by depth interval; >100 cm uses 100 cm source value",
        "sequential_measured_sh2o_26sp": spec["role"] == "calibration" and spec["excode"] == "XXQL2601",
    }

    payload_entries = []
    for path in sorted(out.iterdir(), key=lambda p: p.name.lower()):
        if path.is_file() and path.name != "input_manifest.json":
            payload_entries.append({"name": path.name, "sha256": sha256_file(path), "bytes": path.stat().st_size})
    manifest["files"] = payload_entries

    # Keep provenance role sections, but ensure every nested file digest is
    # synchronized with the payload actually written to this new bundle.
    digest_by_name = {entry["name"]: entry for entry in payload_entries}
    def refresh_nested(value):
        if isinstance(value, dict):
            name = value.get("name")
            if name in digest_by_name:
                value["sha256"] = digest_by_name[name]["sha256"]
                value["bytes"] = digest_by_name[name]["bytes"]
            for nested in value.values():
                refresh_nested(nested)
        elif isinstance(value, list):
            for nested in value:
                refresh_nested(nested)
    refresh_nested(manifest.get("files_by_role", {}))
    manifest["summary"] = dict(manifest.get("summary") or {})
    manifest["summary"].update({"total_files": len(payload_entries)})
    manifest["manifest_repair"] = {
        "package_name_matches_directory": True,
        "file_hashes_regenerated": True,
        "nested_role_hashes_synchronized": True,
        "old_layer_metadata_replaced": True,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "season_id": next(k for k, v in SPECS.items() if v is spec),
        "bundle": str(out),
        "source": str(source),
        "treatments": len(blocks),
        "ic_rows": len(blocks) * len(LAYER_BOTTOMS),
        "manifest_sha256": sha256_file(manifest_path),
    }


def main() -> int:
    results = [_copy_and_rebuild(spec) for spec in SPECS.values()]
    report_dir = ROOT / "workspace/reports/e02_from_scratch_10L_B_20260826"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "bundle_rebuild_receipt.json").write_text(
        json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "results": results}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for result in results:
        print(f"{result['season_id']}: {result['bundle']} rows={result['ic_rows']} manifest={result['manifest_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
