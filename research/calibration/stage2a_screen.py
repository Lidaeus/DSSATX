"""Search the frozen stage-2A parameter box using only training data and W2 gates."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

from f5_26sp import JUNE_29, digest
from forward import evaluate, render_template


def latin_hypercube(rng, members, dimensions):
    return np.column_stack([(rng.permutation(members) + rng.random(members)) / members
                            for _ in range(dimensions)])


def sample(bounds, members, seed, previous):
    rng = np.random.default_rng(seed)
    unit = latin_hypercube(rng, members, len(bounds))
    if previous is not None:
        earlier = pd.read_csv(previous).dropna(subset=["distance_to_w2_gate"])
        within_phi = earlier.loc[earlier.phi_acceptable]
        anchors = pd.concat([
            earlier.nsmallest(4, "distance_to_w2_gate"),
            within_phi.nlargest(2, "leaf_gap_pp"),
            within_phi.nlargest(2, "yield_gap_t_ha"),
        ]).drop_duplicates(subset=list(bounds.index))
        if anchors.empty:
            raise ValueError("Refinement requires successful training evaluations")
        centers = (anchors[bounds.index] - bounds.lower) / (bounds.upper - bounds.lower)
        centers = centers.to_numpy()[np.arange(members) % len(centers)]
        unit = np.clip(centers + (unit - .5) * .55, 0, 1)
    return pd.DataFrame(unit, columns=bounds.index) * (bounds.upper - bounds.lower) + bounds.lower


def inputs(stage):
    observations = pd.read_csv(stage / "observations.csv")
    holdouts = set(pd.read_csv(stage / "holdout.csv").treatment)
    metadata = pd.read_csv(stage / "treatment_metadata.csv")
    reserved = holdouts | set(metadata.loc[metadata.nitrogen_level.eq("N3"), "treatment"])
    if set(observations.treatment) & reserved:
        raise ValueError("Stage 2A training must exclude whole-treatment holdouts and N3")
    w2 = metadata.loc[metadata.water_level.eq("W2")].set_index("nitrogen_level").treatment
    fields = {
        "y": ("FreshWt.OUT", "CHFPW", np.nan, ("N0", "N1", "N2")),
        "lai": ("PlantGro.OUT", "LAID", JUNE_29, ("N0", "N1", "N2")),
        "leaf": ("PlantN.OUT", "LN%D", JUNE_29, ("N1", "N2")),
        "stem": ("PlantN.OUT", "SN%D", JUNE_29, ("N1", "N2")),
    }
    extra = [
        dict(name=f"w2_{key}_{nitrogen.lower()}", file=file, column=column, treatment=w2[nitrogen], yrdoy=date)
        for key, (file, column, date, levels) in fields.items() for nitrogen in levels
    ]
    return observations, pd.concat([observations, pd.DataFrame(extra)], ignore_index=True)


def evaluate_member(engine, stage, observations, targets, phi_limit, out, index, values):
    point = values.to_dict()
    with TemporaryDirectory(prefix="dssat-2a-") as scratch:
        config = Path(scratch) / "NIntegration.nml"
        config.write_text(render_template(stage / "NIntegration.nml.tpl", point), encoding="ascii")
        log = out / "logs" / f"{index:04}.log"
        predicted = pd.Series(evaluate(stage / "inputs", engine, targets, {config: config.name}, log),
                              index=targets.name)
    obs = observations.set_index("name")
    phi = float(((predicted[obs.index] - obs.observed) * obs.weight).pow(2).sum())
    y0, y1, y2 = (float(predicted[f"w2_y_n{level}"]) / 1000 for level in range(3))
    leaf = float(predicted.w2_leaf_n2 - predicted.w2_leaf_n1)
    stem = float(predicted.w2_stem_n2 - predicted.w2_stem_n1)
    lai0, lai1, lai2 = (float(predicted[f"w2_lai_n{level}"]) for level in range(3))
    y = y2 - y1
    eps = 1e-12
    defects = np.array([
        max(0., (3 - y) / 3, (y - 6) / 3),
        max(0., (.25 - leaf - eps) / .25, (leaf - .35 - eps) / .25),
        max(0., (phi - phi_limit) / phi_limit),
        max(0., y0 - y1 + eps, lai0 - lai1 + eps, lai1 - lai2 + eps, -stem + eps),
    ])
    return dict(member=index, **point, phi=phi, phi_acceptable=phi <= phi_limit,
                yield_gap_t_ha=y, leaf_gap_pp=leaf, stem_gap_pp=stem,
                fresh_n0_t_ha=y0, fresh_n1_t_ha=y1, fresh_n2_t_ha=y2,
                lai_n0=lai0, lai_n1=lai1, lai_n2=lai2,
                distance_to_w2_gate=float(np.linalg.norm(defects)), passes_w2=not defects.any())


def screen(engine, stage, reference, out, members, seed, workers, previous, prescribed):
    prior = json.loads(reference.read_text())
    if digest(engine) != prior["engine_sha256"]:
        raise ValueError("The screening engine differs from the archived replay")
    phi_limit = prior["cases"]["control"]["phi"] * 1.10
    bounds = pd.read_csv(stage / "bounds.csv").set_index("name")
    observations, targets = inputs(stage)
    if prescribed is None:
        design = sample(bounds, members, seed, previous)
    else:
        design = pd.read_csv(prescribed, float_precision="round_trip")
        if set(design.columns) != set(bounds.index):
            raise ValueError("A prescribed design must supply exactly the frozen parameter columns")
        design = design.loc[:, bounds.index]
        if design.empty or not ((design >= bounds.lower) & (design <= bounds.upper)).all().all():
            raise ValueError("All design points must be within the frozen parameter bounds")
    out.mkdir(parents=True)
    (out / "logs").mkdir()
    design.to_csv(out / "design.csv", index_label="member")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = [pool.submit(evaluate_member, engine, stage, observations, targets, phi_limit,
                            out, index, values) for index, values in design.iterrows()]
        results = pd.DataFrame([job.result() for job in jobs])
    results.to_csv(out / "screen.csv", index=False)
    receipt = {
        "engine_sha256": prior["engine_sha256"],
        "input_receipt_sha256": digest(stage / "input_receipt.json"),
        "observations_sha256": digest(stage / "observations.csv"),
        "bounds_sha256": digest(stage / "bounds.csv"),
        "previous_screen_sha256": digest(previous) if previous is not None else None,
        "design_sha256": digest(out / "design.csv"),
        "prescribed_design_sha256": digest(prescribed) if prescribed is not None else None,
        "seed": seed, "members": len(results), "phi_limit": phi_limit,
        "passing_w2": results.loc[results.passes_w2, "member"].tolist(),
    }
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("engine", "stage", "reference", "out"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--members", type=int, default=128)
    parser.add_argument("--seed", type=int, default=20261124)
    parser.add_argument("--workers", type=int, default=4)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--refine-from", type=Path)
    source.add_argument("--design", type=Path)
    args = parser.parse_args()
    if args.members < 1 or args.workers < 1:
        parser.error("members and workers must be positive")
    screen(args.engine.resolve(), args.stage.resolve(), args.reference.resolve(), args.out.resolve(),
           args.members, args.seed, args.workers, args.refine_from, args.design)


if __name__ == "__main__":
    main()
