"""Create audited layer-mean FileX bundles using only valid IC groups.

The source bundles are never modified.  The derived FileX files retain the
management, weather, soil and observation assets, remove explicitly invalid
initial-condition blocks, and assign the valid-subset layer means of SH2O,
SNH4 and SNO3 to every retained IC block.  For 25SP IC2--IC13 define the
mean; IC14 is retained as an active treatment but receives that same mean and
IC15 is removed.  For 25FA and 26SP only IC1--IC12 are retained.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "data" / "user" / "experiments"
DERIVATIONS = (
    {
        "season_id": "25SP",
        "source": "xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729",
        "dest": "xxql2501_layermean_ic_valid_n012_v1_20260801",
        "filex": "XXQL2501.TMX",
        "mean_ics": list(range(2, 14)),
        "retain_ics": list(range(2, 15)),
        "remove_ics": [15],
    },
    {
        "season_id": "25FA",
        "source": "xxql2502_actual_trial_calibration_v7_adap34_plantn_slpf_20260729",
        "dest": "xxql2502_layermean_ic_valid_n012_v1_20260801",
        "filex": "XXQL2502.TMX",
        "mean_ics": list(range(1, 13)),
        "retain_ics": list(range(1, 13)),
        "remove_ics": [],
    },
    {
        "season_id": "26SP",
        "source": "xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729",
        "dest": "xxql2601_layermean_ic_valid_n012_v1_20260801",
        "filex": "XXQL2601.TMX",
        "mean_ics": list(range(1, 13)),
        "retain_ics": list(range(1, 13)),
        "remove_ics": [],
    },
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _field(value: float) -> str:
    rendered = format(float(value), ".5g")
    if rendered.startswith("0."):
        rendered = rendered[1:]
    elif rendered.startswith("-0."):
        rendered = "-." + rendered[3:]
    if len(rendered) > 6:
        raise ValueError(f"FileX six-character field overflow: {value}")
    return rendered.rjust(6)


def _is_ic_header(line: str) -> bool:
    return line.strip().upper().startswith("@C") and "PCR" in line.upper() and "ICDAT" in line.upper()


def _is_layer_header(line: str) -> bool:
    upper = line.strip().upper()
    return upper.startswith("@C") and all(x in upper for x in ("ICBL", "SH2O", "SNH4", "SNO3"))


def transform_filex(text: str, *, mean_ics: list[int], retain_ics: list[int], remove_ics: list[int]) -> tuple[str, dict]:
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip().upper().startswith("*INITIAL CONDITIONS")), None)
    if start is None:
        raise ValueError("*INITIAL CONDITIONS section is missing")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("*")), len(lines))

    blocks: list[dict] = []
    i = start + 1
    while i < end:
        if not _is_ic_header(lines[i]):
            i += 1
            continue
        header = i
        row = i + 1
        while row < end and not lines[row].strip() and not lines[row].strip().startswith("*"):
            row += 1
        parts = lines[row].split() if row < end else []
        if not parts or not parts[0].lstrip("+-").isdigit():
            raise ValueError(f"Cannot parse IC header row near line {row + 1}")
        ic = int(parts[0])
        nxt = row + 1
        while nxt < end and not _is_ic_header(lines[nxt]) and not lines[nxt].strip().startswith("*"):
            nxt += 1
        blocks.append({"ic": ic, "header": header, "end": nxt})
        i = nxt
    if not blocks:
        raise ValueError("No IC blocks found")

    all_rows = []
    for block in blocks:
        layer_header = next((j for j in range(block["header"], block["end"]) if _is_layer_header(lines[j])), None)
        if layer_header is None:
            raise ValueError(f"IC{block['ic']} has no layer header")
        j = layer_header + 1
        while j < block["end"] and not lines[j].strip().startswith("*") and not _is_ic_header(lines[j]):
            parts = lines[j].split()
            if len(parts) >= 5 and parts[0].lstrip("+-").isdigit():
                try:
                    all_rows.append({
                        "ic": block["ic"], "depth_cm": int(float(parts[1])),
                        "sh2o": float(parts[2]), "snh4": float(parts[3]), "sno3": float(parts[4]),
                    })
                except ValueError:
                    pass
            j += 1
    selected_rows = [r for r in all_rows if r["ic"] in mean_ics]
    if not selected_rows:
        raise ValueError("No rows remain in the requested mean IC subset")
    depths = sorted({r["depth_cm"] for r in selected_rows})
    means = {
        depth: {key: sum(r[key] for r in selected_rows if r["depth_cm"] == depth) /
                sum(1 for r in selected_rows if r["depth_cm"] == depth)
                for key in ("sh2o", "snh4", "sno3")}
        for depth in depths
    }

    out: list[str] = []
    skip = set()
    block_by_start = {b["header"]: b for b in blocks}
    for idx, line in enumerate(lines):
        if idx in skip:
            continue
        block = block_by_start.get(idx)
        if block is not None and block["ic"] in remove_ics:
            skip.update(range(block["header"], block["end"]))
            continue
        if block is not None and block["ic"] not in retain_ics:
            skip.update(range(block["header"], block["end"]))
            continue
        if idx < start or idx >= end:
            out.append(line)
            continue
        # Replace retained layer rows using fixed-width FileX fields.
        if idx > start:
            parts = line.split()
            if len(parts) >= 5 and parts[0].lstrip("+-").isdigit():
                ic = None
                for b in blocks:
                    if b["header"] < idx < b["end"]:
                        ic = b["ic"]
                        break
                if ic in retain_ics:
                    # Only alter rows with the four layer fields, not the IC header row.
                    try:
                        depth = int(float(parts[1]))
                        float(parts[2]), float(parts[3]), float(parts[4])
                    except (ValueError, IndexError):
                        pass
                    else:
                        if depth in means:
                            out.append(f"{ic:3d}{depth:6d}{_field(means[depth]['sh2o'])}"
                                       f"{_field(means[depth]['snh4'])}{_field(means[depth]['sno3'])}")
                            continue
        out.append(line)

    audit = {
        "mean_ic_ids": mean_ics,
        "retained_ic_ids": retain_ics,
        "removed_ic_ids": remove_ics,
        "source_ic_ids": [b["ic"] for b in blocks],
        "depths_cm": depths,
        "layer_means": [{"depth_cm": d, "SH2O": means[d]["sh2o"], "SNH4": means[d]["snh4"], "SNO3": means[d]["sno3"]} for d in depths],
        "source_layer_row_count": len(all_rows),
        "mean_layer_row_count": len(selected_rows),
    }
    return "\n".join(out) + "\n", audit


def _refresh_manifest(manifest: dict, bundle: Path) -> None:
    for rec in manifest.get("files", []):
        path = bundle / str(rec.get("name", ""))
        if path.is_file():
            rec["sha256"] = sha256(path)
            rec["bytes"] = path.stat().st_size
    for records in manifest.get("files_by_role", {}).values():
        for rec in records:
            path = bundle / str(rec.get("name", ""))
            if path.is_file():
                rec["sha256"] = sha256(path)
                rec["bytes"] = path.stat().st_size


def main() -> int:
    receipts = []
    for spec in DERIVATIONS:
        source = BASE / spec["source"]
        dest = BASE / spec["dest"]
        if dest.exists():
            raise FileExistsError(f"Refusing to overwrite existing bundle: {dest}")
        shutil.copytree(source, dest)
        source_filex = source / spec["filex"]
        filex = dest / spec["filex"]
        transformed, audit = transform_filex(
            filex.read_text(encoding="utf-8"),
            mean_ics=spec["mean_ics"], retain_ics=spec["retain_ics"], remove_ics=spec["remove_ics"],
        )
        filex.write_text(transformed, encoding="utf-8", newline="")
        audit_path = dest / "initial_condition_valid_ic_layermean_audit.json"
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest_path = dest / "input_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.update({
            "bundle_id": dest.name,
            "derived_from_bundle": source.name,
            "derived_from_manifest_sha256": sha256(source / "input_manifest.json"),
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "scenario_type": "valid_ic_layer_mean_initial_condition_calibration",
            "initial_condition_policy": f"{spec['season_id']}: mean of IC{spec['mean_ics'][0]}-IC{spec['mean_ics'][-1]} for SH2O/SNH4/SNO3",
            "filex_fix_status": "Invalid IC blocks removed; retained IC blocks use valid-subset per-layer means.",
            "initial_condition_valid_ic_layermean_audit": {"filex": spec["filex"], **audit},
        })
        _refresh_manifest(manifest, dest)
        manifest.setdefault("files", []).append({
            "name": audit_path.name, "sha256": sha256(audit_path), "bytes": audit_path.stat().st_size,
            "generated_by": "tools/experiments/derive_valid_ic_layermean_bundles_20260801.py",
        })
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        receipts.append({"season_id": spec["season_id"], "bundle": dest.relative_to(ROOT).as_posix(),
                         "filex_sha256": sha256(filex), "manifest_sha256": sha256(manifest_path), **audit})
    print(json.dumps(receipts, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
