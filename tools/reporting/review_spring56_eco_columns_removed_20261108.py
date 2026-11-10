"""Replay the best saved 56-parameter member under the approved majority rule."""

from pathlib import Path
import shutil
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.calibration import run_spring56_eco_columns_removed_200x4_20261107 as control

run = control.RUN
trial, native, gradient = control.trial, control.native, control.gradient


def main():
    design = trial.read(run / "design.json")
    assert native.sha(run / "design.json") == trial.read(run / "sealed_design.json")["sha256"]
    for name, digest in design["source_hashes"].items():
        assert native.sha(Path(name)) == digest, name
    assert trial.read(run / "joint/run_status.json")["status"] == "completed"
    assert not (run / "selection.json").exists()
    trial.MEMBERS, trial.UPDATES = design["members"], design["updates"]
    trial.DATES = design["anthesis_dates"]
    gradient.sa98_joint40.SIGNED.add(gradient.NITROGEN_OPERATOR)
    control.configure_runner()

    bounds = pd.read_csv(design["frozen_bounds"]).rename(columns={"name": "registry_name", "native_name": "name"})
    obs = pd.read_csv(run / "calibration_observations.csv").fillna("")
    initial = pd.read_csv(run / "joint/initial_ensemble.csv", index_col=0)
    assert len(initial) == trial.MEMBERS
    minimum_retained = len(initial) // 2 + 1
    rounds = pd.read_csv(run / "round_quality.csv")
    choices = []
    for row in rounds.itertuples(index=False):
        params = pd.read_csv(run / f"joint/joint.{row.iteration}.par.csv", index_col=0)
        outputs = pd.read_csv(run / f"joint/joint.{row.iteration}.obs.csv", index_col=0)
        members = initial.index.intersection(params.index).intersection(outputs.index)
        residuals = outputs.loc[members, obs.obsnme].to_numpy()
        valid = np.isfinite(residuals).all(axis=1) & np.isfinite(params.loc[members, bounds.pest_name]).all(axis=1)
        scores = pd.Series(np.square(residuals[valid] * obs.final_weight.to_numpy()).sum(axis=1), index=members[valid])
        assert len(scores) == row.retained and np.isclose(scores.min(), row.min_phi, rtol=1e-10)
        if len(scores) >= minimum_retained:
            member = min(scores.index, key=lambda name: (scores[name], name))
            choices.append((float(scores[member]), row.iteration, member, params.loc[member, bounds.pest_name]))
    assert rounds.iloc[-1].retained >= minimum_retained
    score, iteration, member, row = min(choices, key=lambda item: item[:3])
    values = trial.values_for(bounds, dict(zip(bounds.name, row)))
    assert set(values).isdisjoint(control.EXCLUDED)
    ctx = control.contexts(run, design, bounds, ("26SP", "25SP"))
    out, validation = run / "selected_deterministic", run / "validation"
    out.mkdir()
    validation.mkdir()
    compared = trial.evaluate(run, out, ctx["26SP"], values, obs)
    phi = float(compared.phi_contribution.sum())
    assert np.isclose(phi, score, rtol=1e-6), (phi, score)
    compared.to_csv(run / "calibration_comparison.csv", index=False)
    best = run / "best_calibration_parameters.csv"
    pd.Series(values, name="value").to_csv(best, index_label="name")
    trial.simulate(run, validation, ctx["25SP"], values)
    catalog = pd.read_csv(run / "locked_validation_observations.csv").fillna("")
    trial.extract(validation, catalog, strict=False).to_csv(run / "validation_comparison.csv", index=False)
    fruit = trial.observation_catalog(Path(design["datasets"]["26SP"]["path"]), "26SP")
    trial.extract(out, fruit[fruit.variable.eq("FRUIT_N_PCT")], strict=False).to_csv(
        run / "calibration_fruit_n_diagnostic.csv", index=False)
    for path in (out, validation):
        rows = (path / "TMGRO048.ECO").read_text(encoding="ascii").splitlines()
        assert all(name not in line for line in rows for name in control.EXCLUDED)

    shutil.copy2(run / "round_quality.csv", run / "round_quality_original_gate.csv")
    shutil.copy2(run / "pipeline_status.json", run / "pipeline_status_original_gate.json")
    rounds["passed"] = rounds.retained.ge(minimum_retained)
    rounds.to_csv(run / "round_quality.csv", index=False)
    native.write(run / "selection.json", dict(iteration=iteration, member=member, phi=phi, validation_used=False,
                 minimum_retained=minimum_retained, parameters_sha256=native.sha(best)))
    gradient.RUN = run
    gradient.save_gradient_diagnostics(design)
    engineering = trial.read(run / "joint/run_status.json")["engineering_status"]
    retained = int(rounds.iloc[-1].retained)
    trial.status(run, "completed", selected_phi=phi, selected_iteration=int(iteration), selected_member=member,
                 retained=retained, all_rounds_passed=bool(rounds.passed.all()), minimum_retained=minimum_retained,
                 engineering_status=engineering, scientific_status="science_pending_trial",
                 diagnostic_footer=f"trial | majority rule passed | final {retained}/{len(initial)} | original 98% gate missed")
    print(f"Selected iteration {iteration} {member}: Phi {phi:.9f}")


if __name__ == "__main__":
    main()
