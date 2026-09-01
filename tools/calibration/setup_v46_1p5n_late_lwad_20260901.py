"""Prepare controlled v46 1.5x-initial-N calibration arms.

Arm A uses the v46 observation policy. Arm B doubles the multiplier only for
the two final 26SP LWAD increment observations (D26180 and D26198), so a late
LAI/LWAD trade-off can be tested without changing any other objective family.
"""
from __future__ import annotations

import csv
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC_BUNDLES = {
    "25SP": ROOT / "data/user/experiments/xxql2501_formal_scheme4_soil_20260830",
    "26SP": ROOT / "data/user/experiments/xxql2601_formal_scheme4_soil_20260830",
}
OUT_BUNDLES = {
    "25SP": ROOT / "data/user/experiments/xxql2501_scheme4_1p5n_20260901",
    "26SP": ROOT / "data/user/experiments/xxql2601_scheme4_1p5n_20260901",
}
POLICY_SRC = ROOT / "configs/runs/e02_from_scratch_objective_contract_20260826.csv"
REPORT = ROOT / "workspace/reports/e02_v46_1p5n_late_lwad_20260901"
CONFIG_DIR = ROOT / "configs/runs"
BASE_CONFIG = ROOT / "configs/runs/e02_formal_v46_step20_custom26sp_20260831_200x4.json"


def scale_tmx(path: Path, factor: float) -> None:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    in_ic = False
    in_soil_n = False
    out: list[str] = []
    header = re.compile(r"^\s*@C\s+ICBL\s+SH2O\s+SNH4\s+SNO3", re.I)
    data = re.compile(r"^(?P<prefix>\s*\d+\s+\d+\s+[-+.0-9Ee]+\s+)(?P<nh4>[-+.0-9Ee]+)(?P<gap>\s+)(?P<no3>[-+.0-9Ee]+)(?P<tail>.*)$")
    for line in lines:
        stripped = line.strip().upper()
        if stripped.startswith("*INITIAL CONDITIONS"):
            in_ic = True
            in_soil_n = False
        elif in_ic and stripped.startswith("*") and not stripped.startswith("*INITIAL CONDITIONS"):
            in_ic = False
            in_soil_n = False
        if in_ic and header.search(line):
            in_soil_n = True
            out.append(line)
            continue
        if in_soil_n:
            m = data.match(line.rstrip("\r\n"))
            if m:
                nh4 = float(m.group("nh4")) * factor
                no3 = float(m.group("no3")) * factor
                # Keep the original token widths where possible; TMX is
                # whitespace-delimited, but stable alignment helps auditing.
                nh4_s = f"{nh4:.2f}".rjust(len(m.group("nh4")))
                no3_s = f"{no3:.2f}".rjust(len(m.group("no3")))
                line = m.group("prefix") + nh4_s + m.group("gap") + no3_s + m.group("tail") + ("\n" if line.endswith("\n") else "")
        out.append(line)
    path.write_text("".join(out), encoding="utf-8")


def make_bundles() -> None:
    for season, src in SRC_BUNDLES.items():
        dst = OUT_BUNDLES[season]
        if dst.exists():
            lineage = dst / "bundle_lineage_1p5n.json"
            if not lineage.exists():
                raise FileExistsError(f"refusing to overwrite unrecognised bundle: {dst}")
            # Idempotent reruns are allowed after the bundle has been audited.
            continue
        shutil.copytree(src, dst)
        scale_tmx(dst / ("XXQL2501.TMX" if season == "25SP" else "XXQL2601.TMX"), 1.5)
        (dst / "bundle_lineage_1p5n.json").write_text(json.dumps({
            "source_bundle": str(src), "nitrogen_multiplier": 1.5,
            "scaled_fields": ["SNH4", "SNO3"], "scope": "*INITIAL CONDITIONS only",
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_policy() -> tuple[Path, Path]:
    rows = list(csv.DictReader(POLICY_SRC.open("r", encoding="utf-8-sig", newline="")))
    by_group = {r["group"].strip().upper(): r for r in rows}
    base = dict(by_group["LWADDM"])
    base["group"] = "26SP_LWADDM_D26180"
    # The multiseason T8 allocator rewrites group multipliers.  To obtain a
    # date-specific 2x final weight without modifying that allocator, halve
    # the audited sigma (20 -> 10); the allocator then produces exactly 2x
    # weight in the same family-season bucket.
    base["sigma"] = "10.0"
    base["group_multiplier"] = "1.0"
    base["note"] = "2x late 26SP LWAD increment weight via sigma=10 (D26180)"
    late2 = dict(base)
    late2["group"] = "26SP_LWADDM_D26198"
    late2["note"] = "2x late 26SP LWAD increment weight via sigma=10 (D26198)"
    out_b = REPORT / "e02_v46_1p5n_late_lwad2x_observation_policy.csv"
    REPORT.mkdir(parents=True, exist_ok=True)
    fields = rows[0].keys()
    with out_b.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows + [base, late2])
    return POLICY_SRC, out_b


def make_designs(policy_a: Path, policy_b: Path) -> list[dict[str, str]]:
    source = json.loads(BASE_CONFIG.read_text(encoding="utf-8"))
    specs = [
        ("a", "baseline", policy_a),
        ("b", "late_lwad2x", policy_b),
    ]
    manifest: list[dict[str, str]] = []
    for arm, label, policy in specs:
        design = json.loads(json.dumps(source))
        design.update({
            "design_id": f"e02_formal_v46_1p5n_{label}_100x3_20260901",
            "purpose": f"v46 Step20 with 1.5x initial SNH4/SNO3; {label}",
            "initial_condition_policy": "v46 Step20/custom26SP; SNH4 and SNO3 multiplied by 1.5 in copied TMX bundles",
            "observation_policy": str(policy.relative_to(ROOT)),
            "pest_ies": {"num_reals": 100, "noptmax": 3, "agents": 6, "random_seed": 42},
            "seasons": [
                {"season_id": "25SP", "experiment_code": "XXQL2501", "bundle_path": str(OUT_BUNDLES["25SP"].relative_to(ROOT)), "role": "calibration", "treatments": [2,5,10,13]},
                {"season_id": "26SP", "experiment_code": "XXQL2601", "bundle_path": str(OUT_BUNDLES["26SP"].relative_to(ROOT)), "role": "calibration", "treatments": [2,3,11,12]},
            ],
        })
        design["diagnostic_only"] = {"25SP": [3,4,9,11,12,14], "26SP": [1,4,5,6,7,8,9,10]}
        path = CONFIG_DIR / f"e02_formal_v46_1p5n_{label}_100x3_20260901.json"
        path.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest.append({"arm": arm, "label": label, "design": str(path.relative_to(ROOT)), "policy": str(policy.relative_to(ROOT)), "bundle_25sp": str(OUT_BUNDLES["25SP"].relative_to(ROOT)), "bundle_26sp": str(OUT_BUNDLES["26SP"].relative_to(ROOT))})
    (REPORT / "arm_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    make_bundles()
    policy_a, policy_b = make_policy()
    make_designs(policy_a, policy_b)
    print(json.dumps({"bundles": {k: str(v) for k, v in OUT_BUNDLES.items()}, "policy_baseline": str(policy_a), "policy_late_lwad2x": str(policy_b)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
