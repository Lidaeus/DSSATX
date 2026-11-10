"""Freeze the reviewed dual-spring Morris tables for the R Fig3 renderer."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def record(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def export(run, proposal, out, allow_demo=False):
    result_path = run / "results" / "result_manifest.json"
    proposal_path = proposal / "proposal.json"
    result, selection = read_json(result_path), read_json(proposal_path)
    status = result["data_status"]
    if status != "science_validated" and not allow_demo:
        raise ValueError("Morris results are not science_validated; use --allow-unvalidated-demo")
    if selection["run_id"] != run.name:
        raise ValueError("Morris proposal belongs to a different run")
    # The proposal pins the result manifest, so even a same-name replacement
    # of the Morris run cannot be silently combined with the earlier selection.
    result_hashes = {
        Path(path).name: digest
        for path, digest in selection["source_sha256"].items()
    }
    if result_hashes.get(result_path.name) != record(result_path)["sha256"]:
        raise ValueError("Proposal pins a different Morris result manifest")
    tables = {
        run / "results" / "morris_process_scores.csv": result["sha256"],
        proposal / "screening_126_parameters.csv": selection["artifact_sha256"],
        proposal / "proposed_active_parameters.csv": selection["artifact_sha256"],
    }
    sources = [record(result_path), record(proposal_path)]
    for path, hashes in tables.items():
        entry = record(path)
        if entry["sha256"] != hashes.get(path.name):
            raise ValueError(f"Input hash mismatch: {path}")
        sources.append(entry)
    out.mkdir(parents=True, exist_ok=False)
    artifacts = []
    for path in tables:
        target = out / path.name
        shutil.copyfile(path, target)
        artifacts.append({**record(target), "path": target.name})
    manifest = {
        "schema_version": 1,
        "bundle_type": "dual_spring_morris_screening",
        "run_id": run.name,
        "data_status": status,
        "selection_status": selection["status"],
        "n_parameters": result["n_parameters"],
        "paired_trajectories": result["trajectories_per_season"],
        "threshold": 0.98,
        "core_parameters": selection["core_parameters"],
        "supplement_parameters": selection["supplement_parameters"],
        "sources": sources,
        "artifacts": artifacts,
    }
    path = out / "paper_data_manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--proposal-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--allow-unvalidated-demo", action="store_true")
    args = parser.parse_args()
    print(export(args.run_dir.resolve(), args.proposal_dir.resolve(),
                 args.out_dir.resolve(), args.allow_unvalidated_demo))
