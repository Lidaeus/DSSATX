"""Tests for audited transforms and treatment-mean uncertainty."""

import json
import math

import pandas as pd
import pytest

from src.calibration.observation_policy import (
    POLICY_VERSION,
    apply_observation_policy,
    apply_transform_config,
    effective_sigma_for_mean,
    transform_sigma,
    transform_value,
)


def test_effective_sigma_for_treatment_mean_includes_discrepancy_and_floor():
    sigma = effective_sigma_for_mean(
        6.0,
        4,
        n_effective=3.0,
        model_sigma=2.0,
        sigma_floor=1.0,
    )
    assert sigma == pytest.approx(math.sqrt(36.0 / 3.0 + 4.0 + 1.0))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"replicate_sd": 1.0, "n_replicates": 1},
        {"replicate_sd": 1.0, "n_replicates": 3, "n_effective": 4},
        {"replicate_sd": -1.0, "n_replicates": 3},
    ],
)
def test_invalid_treatment_mean_sigma_fails(kwargs):
    with pytest.raises(ValueError):
        effective_sigma_for_mean(**kwargs)


def test_log_transform_uses_same_definition_and_rejects_nonpositive_shift():
    assert transform_value(9.0, "log", offset=1.0, reference=10.0) == pytest.approx(0.0)
    assert transform_sigma(9.0, 2.0, "log", offset=1.0) == pytest.approx(
        math.sqrt(math.log1p(0.2**2))
    )
    with pytest.raises(ValueError, match=r"value \+ offset"):
        transform_value(0.0, "log")


def test_policy_transforms_observation_and_pest_output_identically(tmp_path):
    obs = pd.DataFrame(
        [
            {
                "obsnme": "PWAIS_R1_H1",
                "obsval": 9.0,
                "raw_obsval": 9.0,
                "weight": 0.5,
                "obgnme": "PWAIM_H1",
                "sigma": 2.0,
                "sim_token": "PWAIS",
                "model_output_file": "PestHarvest.OUT",
            }
        ]
    )
    policies = {
        "PWAIM": {
            "group": "PWAIM",
            "transform": "log",
            "offset": "1",
            "reference": "10",
            "sigma_source": "replicate_mean",
            "group_multiplier": "1.1",
        }
    }
    transformed, token_map = apply_observation_policy(obs, policies)
    row = transformed.iloc[0]
    assert row["obsval"] == pytest.approx(0.0)
    assert row["raw_obsval"] == pytest.approx(9.0)
    assert row["sigma_source"] == "replicate_mean"
    assert row["weight"] == pytest.approx(1.1 / math.sqrt(math.log1p(0.2**2)))

    output = tmp_path / "PestHarvest.OUT"
    output.write_text("RUN 1 HNO 1 @PWAIS@ 14.0\n", encoding="utf-8")
    config = tmp_path / "transforms.json"
    config.write_text(
        json.dumps({"version": POLICY_VERSION, "files": token_map}), encoding="utf-8"
    )
    apply_transform_config(config, tmp_path)
    simulated = float(output.read_text(encoding="utf-8").split()[-1])
    assert simulated == pytest.approx(math.log(15.0 / 10.0))


def test_log_policy_requires_auditable_raw_sigma():
    obs = pd.DataFrame(
        [
            {
                "obsnme": "x",
                "obsval": 2.0,
                "weight": 1.0,
                "obgnme": "LWADM",
                "sigma": None,
                "sim_token": "LWADS",
                "model_output_file": "PestTmtGrow.OUT",
            }
        ]
    )
    with pytest.raises(ValueError, match="auditable raw sigma"):
        apply_observation_policy(obs, {"LWADM": {"transform": "log"}})


def test_multiseason_group_uses_unscoped_policy_and_diagnostic_is_zero_weight():
    obs = pd.DataFrame([{
        "obsnme": "25SP_HWAMS_R1",
        "obsval": 100.0,
        "weight": 1.0,
        "obgnme": "25SP_HWAMM",
        "sigma": 50.0,
        "sim_token": "HWAMS",
        "model_output_file": "PestJoint.OUT",
    }])
    transformed, _ = apply_observation_policy(obs, {
        "HWAMM": {"sigma": "50", "phi_role": "diagnostic_only"}
    })
    assert transformed.iloc[0]["phi_role"] == "diagnostic_only"
    assert transformed.iloc[0]["weight"] == 0.0
