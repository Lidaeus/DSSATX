"""Activate the archived 61-parameter design on the audited dual-season 2A objective."""

import argparse
import json
from pathlib import Path
import re
import shutil

import pandas as pd

from crop_cards import read_map
from f5_26sp import digest
from forward import render_template
from prepare_26sp_signal import replace_assignment


def prepare(suite, design_path, out):
    stage = suite / "stage"
    replay = suite / "replay"
    source = json.loads((stage / "stage_receipt.json").read_text())
    anchor = json.loads((replay / "receipt.json").read_text())
    config = replay / "configs/NIntegration.nml"
    if (not source.get("n21_fresh_contrasts") or source["engine_sha256"] != anchor["engine_sha256"]
            or digest(config) != anchor["rendered_config_sha256"][config.name]):
        raise ValueError("Use a verified 2A N2-N1 stage and its selected native replay")
    for name, expected in source["files_sha256"].items():
        if digest(stage / name) != expected:
            raise ValueError(f"Changed source input: {name}")
    design = pd.read_csv(design_path, keep_default_na=False).set_index("name", verify_integrity=True)
    mechanism = design.file.eq("NIntegration.nml")
    if len(design) != 61 or int(mechanism.sum()) != 20:
        raise ValueError("Expected 41 crop parameters and 20 mechanism parameters")
    first_stage_bounds = pd.read_csv(stage / "bounds.csv").set_index("name")
    edits = {"q_no3_max": "upper", "pool_beta": "lower"}
    bound_changes = {}
    for alias, endpoint in edits.items():
        replacement = float(first_stage_bounds.loc[alias, endpoint])
        bound_changes[alias] = {"side": endpoint, "old": float(design.loc[alias, endpoint]), "new": replacement}
        design.loc[alias, endpoint] = replacement

    start = config.read_text()
    text = start
    for alias, row in design.loc[mechanism].iterrows():
        match = re.search(rf"(?im)^[^!\n]*?\b{re.escape(row.field)}\s*=\s*([-+.\dEeDd]+)", start)
        if not match:
            raise ValueError(f"Missing selected value for {alias}")
        design.loc[alias, "init"] = float(match[1].lower().replace("d", "e"))
        text, count = replace_assignment(text, row.field, f"~ {alias:25s} ~")
        if count != 1:
            raise ValueError(f"Expected one active assignment for {alias}")

    out.mkdir(parents=True, exist_ok=False)
    crop_map = out / "crop_map.csv"
    design.loc[~mechanism, ["file", "record", "field"]].to_csv(crop_map)
    plan_a, plan_b = [read_map(crop_map, stage / "inputs" / d, design) for d in ("s25", "s26")]
    if plan_a != plan_b:
        raise ValueError("The two trials do not use the same editable crop records")
    for entry in plan_a.values():
        for field in entry["fields"]:
            design.loc[field["name"], "init"] = field["baseline"]
    if not design.init.between(design.lower, design.upper).all():
        raise ValueError(f"Selected starting point outside bounds: {design.loc[~design.init.between(design.lower, design.upper)]}")
    template = out / "NIntegration.nml.tpl"
    template.write_text("ptf ~\n" + text, encoding="ascii")
    if re.sub(r"\s+", "", render_template(template, design.init)) != re.sub(r"\s+", "", start):
        raise ValueError("Initial rendered mechanism differs from the verified 2A selection")
    shutil.copytree(stage / "inputs", out / "inputs")
    for name in ("observations.csv", "all_observations.csv", "phase_b_observations.csv"):
        shutil.copyfile(stage / name, out / name)
    design[["init", "lower", "upper"]].to_csv(out / "bounds.csv")
    design.to_csv(out / "parameter_design.csv")
    receipt = dict(source)
    receipt.update(source_stage_sha256=digest(stage / "stage_receipt.json"), design_sha256=digest(design_path),
                   anchor_receipt_sha256=digest(replay / "receipt.json"), anchor_config_sha256=digest(config),
                   parameter_count={"crop_cards": 41, "mechanism": 20}, bounds_changes=bound_changes,
                   files_sha256={str(p.relative_to(out)): digest(p) for p in out.rglob("*") if p.is_file()})
    (out / "stage_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("suite", "design-path", "out"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    prepare(**vars(parser.parse_args()))
