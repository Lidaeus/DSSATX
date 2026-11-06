from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.sensitivity import sobol_repair


def _synthetic_source(root: Path) -> Path:
    source = root / "source"
    source.mkdir()
    parameters = pd.DataFrame(
        {
            "run_id": range(6),
            "p1": [0.1, 0.2, 0.8, 0.9, 0.8, 0.9],
        }
    )
    outputs = pd.DataFrame(
        {
            "run_id": range(6),
            "failed_flag": [0, 0, 0, 0, 1, 0],
            "yield": [1.0, 2.0, 3.0, 4.0, 999.0, 8.0],
            "structural_zero": [5.0] * 6,
        }
    )
    parameters.to_csv(source / "sa_sen_sobol.sobol.par.csv", index=False)
    outputs.to_csv(source / "sa_sen_sobol.sobol.obs.csv", index=False)
    bad_si, bad_st = sobol_repair.recompute_indices(parameters, outputs, samples=2)
    bad_si.to_csv(source / "sa_sen_sobol.sobol.si.csv", index=False)
    bad_st.to_csv(source / "sa_sen_sobol.sobol.sti.csv", index=False)
    (source / "sa_sen_sobol.pst").write_text("++gsa_method(sobol)\n", encoding="utf-8")
    (source / "sa_sen_sobol.rec").write_text("PESTPP-SEN analysis complete\n", encoding="utf-8")
    (source / "sa_obs_order.txt").write_text("yield\nstructural_zero\n", encoding="utf-8")
    (source / "run_manifest.yaml").write_text(
        "run_id: original\n"
        "run_type: sensitivity_sobol_formal_case\n"
        "sensitivity_method: sobol\n"
        "cultivar: TM0008\n"
        "sobol_samples: 2\n"
        "sobol_parameter_count: 1\n"
        "sobol_expected_model_runs: 6\n"
        "observation_count: 2\n",
        encoding="utf-8",
    )
    (source / "run_status.json").write_text(
        json.dumps({"status": "completed", "scientific_status": "failed", "n_agents": 2}),
        encoding="utf-8",
    )
    return source


def test_recompute_indices_uses_saltelli_blocks():
    parameters = pd.DataFrame({"run_id": range(6), "p1": range(6)})
    outputs = pd.DataFrame(
        {
            "run_id": range(6),
            "failed_flag": [0] * 6,
            "y": [1.0, 2.0, 3.0, 4.0, 2.0, 5.0],
        }
    )
    si, st = sobol_repair.recompute_indices(parameters, outputs, samples=2)
    variance = np.var([1.0, 2.0, 3.0, 4.0])
    assert si.loc[0, "p1"] == pytest.approx(np.mean(np.array([3.0, 4.0]) * np.array([1.0, 3.0])) / variance)
    assert st.loc[0, "p1"] == pytest.approx(0.5 * np.mean(np.array([-1.0, -3.0]) ** 2) / variance)


def test_repair_case_replays_twice_and_keeps_source_immutable(tmp_path: Path, monkeypatch):
    source = _synthetic_source(tmp_path)
    source_obs_hash = hashlib.sha256((source / "sa_sen_sobol.sobol.obs.csv").read_bytes()).hexdigest()
    calls: list[Path] = []

    def fake_replay(_source: Path, replay_dir: Path, _row: pd.Series):
        calls.append(replay_dir)
        vector = np.array([6.0, 5.0])
        return vector, {
            "returncode": 0,
            "parameter_sha256": "parameter",
            "response_sha256": "same-response",
            "stdout_sha256": "stdout",
            "stderr_sha256": "stderr",
            "response_count": 2,
        }

    monkeypatch.setattr(sobol_repair, "_execute_replay", fake_replay)
    destination = tmp_path / "derived"
    result = sobol_repair.repair_case(source, destination)

    assert len(calls) == 2
    assert result["failed_run_ids"] == [4]
    repaired = pd.read_csv(destination / "sa_sen_sobol.sobol.obs.csv")
    assert repaired.loc[4, "failed_flag"] == 0
    assert repaired.loc[4, "yield"] == 6.0
    assert json.loads((destination / "run_status.json").read_text())["scientific_status"] == "validated"
    assert hashlib.sha256((source / "sa_sen_sobol.sobol.obs.csv").read_bytes()).hexdigest() == source_obs_hash


def test_repair_maps_replay_values_by_observation_name(tmp_path: Path, monkeypatch):
    source = _synthetic_source(tmp_path)
    outputs_path = source / "sa_sen_sobol.sobol.obs.csv"
    outputs = pd.read_csv(outputs_path)
    outputs = outputs[["run_id", "failed_flag", "structural_zero", "yield"]]
    outputs.to_csv(outputs_path, index=False)
    bad_si, bad_st = sobol_repair.recompute_indices(
        pd.read_csv(source / "sa_sen_sobol.sobol.par.csv"), outputs, samples=2
    )
    bad_si.to_csv(source / "sa_sen_sobol.sobol.si.csv", index=False)
    bad_st.to_csv(source / "sa_sen_sobol.sobol.sti.csv", index=False)

    def fake_replay(_source: Path, _replay_dir: Path, _row: pd.Series):
        # Replay vector follows sa_obs_order.txt: yield, structural_zero.
        return np.array([6.0, 5.0]), {
            "returncode": 0,
            "parameter_sha256": "parameter",
            "response_sha256": "same-response",
            "stdout_sha256": "stdout",
            "stderr_sha256": "stderr",
            "response_count": 2,
        }

    monkeypatch.setattr(sobol_repair, "_execute_replay", fake_replay)
    destination = tmp_path / "derived"
    sobol_repair.repair_case(source, destination)

    repaired = pd.read_csv(destination / "sa_sen_sobol.sobol.obs.csv")
    assert repaired.loc[4, "yield"] == 6.0
    assert repaired.loc[4, "structural_zero"] == 5.0


def test_repair_rejects_nonidentical_repeats(tmp_path: Path, monkeypatch):
    source = _synthetic_source(tmp_path)
    counter = iter((1.0, 2.0))

    def fake_replay(_source: Path, _replay_dir: Path, _row: pd.Series):
        value = next(counter)
        vector = np.array([value, 5.0])
        return vector, {
            "returncode": 0,
            "parameter_sha256": "parameter",
            "response_sha256": f"response-{value}",
            "stdout_sha256": "stdout",
            "stderr_sha256": "stderr",
            "response_count": 2,
        }

    monkeypatch.setattr(sobol_repair, "_execute_replay", fake_replay)
    with pytest.raises(ValueError, match="not identical"):
        sobol_repair.repair_case(source, tmp_path / "derived")
