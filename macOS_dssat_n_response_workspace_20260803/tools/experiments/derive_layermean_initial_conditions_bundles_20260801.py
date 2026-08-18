"""Create counterfactual bundles with season-wide layer-mean FileX IC values.

The source bundles remain untouched.  For each season, every declared initial
condition level receives the mean SH2O, SNH4 and SNO3 at each layer, calculated
from the source FileX.  All observations, management, weather and soil files
are copied byte-for-byte; only the FileX initial-condition layer rows change.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "data" / "user" / "experiments"
DERIVATIONS = (
    ("25SP", "xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729", "xxql2501_layermean_ic_v1_20260801", "XXQL2501.TMX"),
    ("26SP", "xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729", "xxql2601_layermean_ic_v1_20260801", "XXQL2601.TMX"),
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _field(value: float) -> str:
    # FileX's SH2O/SNH4/SNO3 fields are six characters wide; five
    # significant digits preserves more information than the source's
    # three-decimal values while remaining representable (e.g. .21871).
    rendered = format(float(value), ".5g")
    if rendered.startswith("0."):
        rendered = rendered[1:]
    elif rendered.startswith("-0."):
        rendered = "-." + rendered[3:]
    if len(rendered) > 6:
        raise ValueError(f"Value does not fit FileX field width: {value}")
    return rendered.rjust(6)


def transform_filex(text: str) -> tuple[str, dict[str, object]]:
    lines = text.splitlines()
    in_initial = False
    layer_header = False
    rows: list[dict[str, float | int]] = []
    for i, line in enumerate(lines):
        upper = line.strip().upper()
        if upper.startswith("*INITIAL CONDITIONS"):
            in_initial = True
            continue
        if in_initial and upper.startswith("*"):
            break
        if not in_initial:
            continue
        if upper.startswith("@C") and all(t in upper for t in ("ICBL", "SH2O", "SNH4", "SNO3")):
            layer_header = True
            continue
        if upper.startswith("@C"):
            layer_header = False
            continue
        if not layer_header:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            ic, depth = int(parts[0]), int(float(parts[1]))
            sh2o, snh4, sno3 = map(float, parts[2:5])
        except ValueError:
            continue
        rows.append({"line_index": i, "ic": ic, "depth_cm": depth,
                     "old_sh2o": sh2o, "old_snh4": snh4, "old_sno3": sno3})
    if not rows:
        raise ValueError("No initial-condition layer rows found")
    depths = sorted({int(r["depth_cm"]) for r in rows})
    means: dict[int, dict[str, float]] = {}
    for d in depths:
        group = [r for r in rows if int(r["depth_cm"]) == d]
        means[d] = {k: sum(float(r[k]) for r in group) / len(group)
                    for k in ("old_sh2o", "old_snh4", "old_sno3")}
    audit_rows = []
    for r in rows:
        i = int(r["line_index"])
        d = int(r["depth_cm"])
        m = means[d]
        lines[i] = f"{int(r['ic']):3d}{d:6d}{_field(m['old_sh2o'])}{_field(m['old_snh4'])}{_field(m['old_sno3'])}"
        audit_rows.append({
            "ic": int(r["ic"]), "depth_cm": d,
            "old_sh2o": float(r["old_sh2o"]), "old_snh4": float(r["old_snh4"]), "old_sno3": float(r["old_sno3"]),
            "new_sh2o": m["old_sh2o"], "new_snh4": m["old_snh4"], "new_sno3": m["old_sno3"],
        })
    audit = {
        "row_count": len(rows),
        "ic_count": len({int(r["ic"]) for r in rows}),
        "depths_cm": depths,
        "layer_means": [{"depth_cm": d, "SH2O": means[d]["old_sh2o"],
                         "SNH4": means[d]["old_snh4"], "SNO3": means[d]["old_sno3"]}
                        for d in depths],
        "rows": audit_rows,
    }
    return "\n".join(lines) + "\n", audit


def _refresh(record: dict, bundle: Path) -> None:
    name = str(record.get("name") or "")
    path = bundle / name
    if path.is_file():
        record["sha256"] = sha256(path)
        record["bytes"] = path.stat().st_size


def main() -> int:
    receipts = []
    for season, source_name, dest_name, filex_name in DERIVATIONS:
        source = BASE / source_name
        dest = BASE / dest_name
        if dest.exists():
            raise FileExistsError(f"Refusing to overwrite existing bundle: {dest}")
        shutil.copytree(source, dest)
        source_manifest = source / "input_manifest.json"
        filex = dest / filex_name
        transformed, audit = transform_filex(filex.read_text(encoding="utf-8"))
        filex.write_text(transformed, encoding="utf-8", newline="")
        (dest / "initial_condition_layermean_audit.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        manifest_path = dest / "input_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update({
            "bundle_id": dest.name,
            "derived_from_bundle": source.name,
            "derived_from_manifest_sha256": sha256(source_manifest),
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "scenario_type": "counterfactual_layer_mean_initial_condition_calibration",
            "initial_condition_policy": "season_layer_mean_of_source_FileX_SH2O_SN H4_SNO3".replace(" ", ""),
            "filex_fix_status": "Derived FileX: SH2O/SNH4/SNO3 replaced by season-wide layer means; all other sections retained.",
            "initial_condition_layermean_audit": {
                "filex": filex_name,
                "source_filex_sha256": sha256(source / filex_name),
                **audit,
            },
        })
        transforms = list(manifest.get("counterfactual_transformations") or [])
        transforms.append({
            "transformation_id": "season_layer_mean_initial_conditions_v1_20260801",
            "section": "*INITIAL CONDITIONS",
            "fields": ["SH2O", "SNH4", "SNO3"],
            "scope": "all IC groups, each declared depth receives the season-wide mean",
            "unchanged": ["ICDAT", "fertilizer management", "irrigation management", "weather", "SOIL.SOL", "observations", "*SOIL ANALYSIS"],
            "row_count": audit["row_count"],
            "layer_means": audit["layer_means"],
        })
        manifest["counterfactual_transformations"] = transforms
        for rec in manifest.get("files", []):
            _refresh(rec, dest)
        for records in manifest.get("files_by_role", {}).values():
            for rec in records:
                _refresh(rec, dest)
        manifest.setdefault("files", []).append({
            "name": "initial_condition_layermean_audit.json",
            "sha256": sha256(dest / "initial_condition_layermean_audit.json"),
            "bytes": (dest / "initial_condition_layermean_audit.json").stat().st_size,
            "generated_by": "tools/experiments/derive_layermean_initial_conditions_bundles_20260801.py",
        })
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        receipts.append({"season_id": season, "bundle": dest.relative_to(ROOT).as_posix(),
                         "filex_sha256": sha256(filex), "manifest_sha256": sha256(manifest_path),
                         "layer_means": audit["layer_means"], "row_count": audit["row_count"]})
    print(json.dumps(receipts, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
