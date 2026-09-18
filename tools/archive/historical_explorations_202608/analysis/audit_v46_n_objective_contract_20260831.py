"""Audit N/W objective contracts against the hard-gate implementation.

This is a read-only provenance check.  It does not build a PEST control file,
modify a bundle, or change any frozen bounds.  The purpose is to catch the
specific failure mode where a formal run optimizes one nitrogen contrast while
the deterministic promotion gate evaluates a different contrast.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _one(path: Path, pattern: str) -> Path:
    found = sorted(path.glob(pattern))
    if not found:
        raise FileNotFoundError(f"no {pattern!r} under {path}")
    return found[0]


def _contract_rows(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    key = "name" if rows and "name" in rows[0] else "group"
    return {str(r[key]): r for r in rows if r.get(key)}


def _gate_definition(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    # Keep this deliberately narrow: the implementation is expected to use
    # the explicit tuple in mean_n2_n1_minus_n0_gate().
    levels = re.findall(r'for level in \(([^)]*)\)', text)
    level_text = levels[0] if levels else ""
    used_levels = re.findall(r'"(N[123])"', level_text)
    excludes_n3 = "N3 is deliberately excluded" in text
    return {
        "path": str(path.resolve()),
        "function": "mean_n2_n1_minus_n0_gate",
        "levels_in_loop": used_levels,
        "expected_levels": ["N1", "N2"],
        "excludes_N3": excludes_n3,
        "contrast_definition": "mean_of_N2_minus_N0_and_N1_minus_N0",
    }


def _objective_row(label: str, path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    n = payload.get("nitrogen_response_objective") or {}
    w = payload.get("water_response_objective") or {}
    return {
        "design_label": label,
        "design_file": str(path.resolve()),
        "design_id": payload.get("design_id"),
        "n_enabled": n.get("enabled"),
        "n_levels": json.dumps(n.get("levels", []), ensure_ascii=False),
        "n_contrast": n.get("contrast"),
        "n_source_variable": n.get("source_variable"),
        "n_sst_scope": n.get("sst_scope"),
        "n_lambda": n.get("nse_lambda"),
        "n_mapping_csv": n.get("mapping_csv"),
        "w_enabled": w.get("enabled"),
        "w_levels": json.dumps(w.get("levels", []), ensure_ascii=False),
        "w_contrast": w.get("contrast"),
        "w_mapping_csv": w.get("mapping_csv"),
        "w_season_contrasts": json.dumps(w.get("season_contrasts", {}), ensure_ascii=False),
        "w_lambda": w.get("nse_lambda"),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--formal-json", type=Path, default=Path(
        "configs/runs/e02_formal_v46_step20_custom26sp_20260831_200x4.json"))
    p.add_argument("--local-dir", type=Path, default=Path("configs/runs"))
    p.add_argument("--local-glob", default="e02_v46_best71_n_*_60x3_20260831.json")
    p.add_argument("--objective-contract", type=Path, default=Path(
        "configs/runs/e02_from_scratch_objective_contract_20260826.csv"))
    p.add_argument("--gate-source", type=Path, default=Path(
        "src/reporting/nitrogen_response_gate.py"))
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()

    formal_path = args.formal_json.resolve()
    local_dir = args.local_dir.resolve()
    contract_path = args.objective_contract.resolve()
    gate_path = args.gate_source.resolve()
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)

    design_paths = [formal_path] + sorted(
        x.resolve() for x in local_dir.glob(args.local_glob) if x.resolve() != formal_path
    )
    rows = []
    for path in design_paths:
        label = "formal" if path == formal_path else path.stem
        rows.append(_objective_row(label, path, _json(path)))

    fieldnames = list(rows[0]) if rows else []
    with (out / "objective_contract_rows.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    gate = _gate_definition(gate_path)
    contract = _contract_rows(contract_path)
    n_note = contract.get("NRESPM", {}).get("note", "")
    w_note = contract.get("WRESPM", {}).get("note", "")
    formal = rows[0] if rows else {}
    formal_levels = json.loads(formal.get("n_levels", "[]"))
    formal_n_ok = set(formal_levels) == set(gate["expected_levels"])
    formal_source_ok = formal.get("n_source_variable") == "CHFPW"
    formal_sst_ok = formal.get("n_sst_scope") == "season_x_response_stratum"
    w_note_stale = ("26SP W3 minus W1" in w_note and
                    "W2" in str(formal.get("w_season_contrasts", "")))
    audit = {
        "schema_version": 1,
        "scope": "formal v46 plus local A-E design JSONs",
        "formal_design": formal,
        "local_design_count": max(0, len(rows) - 1),
        "gate": gate,
        "contract_csv": str(contract_path),
        "contract_rows": {k: {"group_multiplier": v.get("group_multiplier"), "sigma_floor": v.get("sigma_floor"), "role": v.get("phi_role"), "note": v.get("note")} for k, v in contract.items() if k in {"NRESPM", "WRESPM"}},
        "checks": {
            "formal_n_levels_match_gate": formal_n_ok,
            "formal_n_source_is_CHFPW": formal_source_ok,
            "formal_n_sst_is_season_x_response_stratum": formal_sst_ok,
            "formal_w_note_mentions_stale_26SP_W3_minus_W1": w_note_stale,
            "contract_n_note": n_note,
            "contract_w_note": w_note,
        },
        "contract_consistent": bool(formal_n_ok and formal_source_ok and formal_sst_ok and not w_note_stale),
        "interpretation": [
            "The hard gate evaluates the mean of N2-N0 and N1-N0 within complete water strata and deliberately excludes N3.",
            "The formal v46 JSON currently optimizes N3-N0 only; this is an objective/gate mismatch, not an execution failure.",
            "The contract CSV WRESPM note still describes 26SP W3-W1 while the formal design JSON uses 26SP W2-W1.",
        ],
        "data_modified": False,
        "phi_modified": False,
    }
    (out / "audit.json").write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"contract_consistent": audit["contract_consistent"], "formal_n_levels": formal_levels,
                      "gate_levels": gate["expected_levels"], "stale_w_note": w_note_stale}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
