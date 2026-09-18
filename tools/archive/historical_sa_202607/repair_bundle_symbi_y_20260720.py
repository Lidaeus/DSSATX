"""Repair the OPTIONS-row fixed-width alignment AND set SYMBI=Y in the three
controlled bundles.

Two issues found during the T1 baseline smoke are remedied here:

1. Fixed-width OPTIONS-row alignment: the original bundle's @N OPTIONS data
   row had been collapsed to space-delimited tokens by a bug in
   tools/import_experiment_bundle._set_simulation_option, which made DSSAT
   mis-read POTAS/CO2 columns. The bug is fixed in _set_simulation_option (it
   now rebuilds the row in fixed-width form).

2. SYMBI must be Y for CRGRO: A/B testing in CWD=TMD with explicit CRGRO048
   proved DSSAT's CRGRO (tomato) model aborts at startup with IPSIM
   "Potassium model has not been enabled for CRGRO" whenever SYMBI=N
   (SYMBI=N -> exit 99, 0 rows; SYMBI=Y -> exit 0, 8 rows). The earlier
   handoff decision to set SYMBI=N ("eggplant is non-legume") is reversed for
   the tomato-model-on-eggplant case: actual N fixation is disabled by fixing
   the FRCNOD species parameter at 0.05, not by toggling SYMBI.

This script applies both repairs to each bundle FileX (OPTIONS alignment is
already fixed by a prior run, so only SYMBI Y is applied here unless the
OPTIONS row is still collapsed) and updates each bundle's input_manifest.json
with a repair_history entry + refreshed SHA-256. ``verify_manifest_integrity``
passes afterwards.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.import_experiment_bundle import _set_simulation_option

BUNDLES = [
    {"exp": "XXQL2501", "bundle": "xxql2501_sa_controlled_candidate_20260720"},
    {"exp": "XXQL2502", "bundle": "xxql2502_sa_controlled_candidate_20260720"},
    {"exp": "XXQL2601", "bundle": "xxql2601_sa_controlled_candidate_20260720"},
]

REPAIR_REASON = (
    "SYMBI=Y repair: A/B testing proved DSSAT CRGRO (tomato) aborts with IPSIM "
    "'Potassium model has not been enabled for CRGRO' whenever SYMBI=N. The "
    "handoff's SYMBI=N (eggplant non-legume) decision is reversed for the "
    "tomato-model-on-eggplant case; actual N fixation is disabled by fixing "
    "FRCNOD=0.05, not by SYMBI. _set_simulation_option(SYMBI=Y) both sets the "
    "value and (re)confirms the fixed-width OPTIONS row alignment."
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _options_data_row(path: Path) -> str:
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="ignore").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.strip().upper().startswith("@N OPTIONS") and i + 1 < len(lines):
            return lines[i + 1].rstrip()
    return ""


def _update_manifest(bundle_dir: Path, filex_name: str, repair_record: dict) -> dict:
    manifest_path = bundle_dir / "input_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    new_sha = _sha256(bundle_dir / filex_name)
    new_bytes = (bundle_dir / filex_name).stat().st_size
    for entry in manifest.get("files", []):
        if entry.get("name") == filex_name:
            entry["previous_sha256"] = entry.get("sha256")
            entry["sha256"] = new_sha
            entry["bytes"] = new_bytes
            break
    history = manifest.setdefault("repair_history", [])
    history.append(repair_record)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return manifest


def repair_one(entry: dict) -> dict:
    bundle_dir = PROJECT_ROOT / "data" / "user" / "experiments" / entry["bundle"]
    filex_name = f"{entry['exp']}.TMX"
    filex = bundle_dir / filex_name
    before_sha = _sha256(filex)
    before_row = _options_data_row(filex)

    record = {
        "exp": entry["exp"],
        "bundle": entry["bundle"],
        "filex": str(filex),
        "before_sha256": before_sha,
        "before_options_row": before_row,
        "reason": REPAIR_REASON,
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    changed = _set_simulation_option(filex, "SYMBI", "Y")
    after_row = _options_data_row(filex)
    after_sha = _sha256(filex)
    record["rows_changed"] = changed
    record["after_sha256"] = after_sha
    record["after_options_row"] = after_row

    manifest = _update_manifest(bundle_dir, filex_name, {
        "file": filex_name,
        "before_sha256": before_sha,
        "after_sha256": after_sha,
        "before_options_row": before_row,
        "after_options_row": after_row,
        "reason": REPAIR_REASON,
        "timestamp_utc": record["timestamp_utc"],
    })
    record["manifest_updated"] = True
    record["manifest_sha256"] = _sha256(bundle_dir / "input_manifest.json")
    return record


def main():
    raise SystemExit(
        "Retired: the approved non-legume eggplant policy is SYMBI=N and POTAS=N. "
        "Do not generate or repair formal bundles to SYMBI=Y."
    )
    records = []
    for entry in BUNDLES:
        rec = repair_one(entry)
        records.append(rec)
        print(json.dumps(rec, indent=2, ensure_ascii=False))

    from src.common.input_manifest import verify_manifest_integrity
    print("\n=== Post-repair manifest integrity ===")
    all_ok = True
    for entry in BUNDLES:
        bundle_dir = PROJECT_ROOT / "data" / "user" / "experiments" / entry["bundle"]
        try:
            verify_manifest_integrity(bundle_dir)
            print(f"  {entry['bundle']}: PASS")
        except Exception as exc:
            print(f"  {entry['bundle']}: FAIL — {exc}")
            all_ok = False

    out = PROJECT_ROOT / "data" / "user" / "experiments" / "_bundle_repair_symbi_y_20260720.json"
    out.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nWrote repair audit: {out}")
    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
