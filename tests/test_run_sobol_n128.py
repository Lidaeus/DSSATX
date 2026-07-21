from __future__ import annotations

import json
from pathlib import Path
import sys

from tools.sa.run_sobol_n128_20260721 import SAMPLES, _append_campaign_case, _run


def test_append_campaign_adds_only_preregistered_n128_once(tmp_path: Path):
    manifest = tmp_path / "formal_sobol_campaign.json"
    manifest.write_text(
        json.dumps(
            {
                "planned_sample_schedule": [64, 128, 256],
                "built_sample_schedule": [64],
                "parameter_count": 23,
                "expected_initial_model_runs": 1600,
                "cases": [
                    {
                        "base_samples": 64,
                        "parameter_count": 23,
                        "expected_model_runs": 1600,
                        "case_dir": str(tmp_path / "n0064"),
                        "pst_sha256": "old",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    case = tmp_path / "n0128"
    case.mkdir()
    pst = case / "sa_sen_sobol.pst"
    pst.write_text("pest control", encoding="utf-8")

    _append_campaign_case(manifest, case, pst)
    _append_campaign_case(manifest, case, pst)
    campaign = json.loads(manifest.read_text(encoding="utf-8"))

    assert SAMPLES == 128
    assert campaign["built_sample_schedule"] == [64, 128]
    assert [item["base_samples"] for item in campaign["cases"]] == [64, 128]
    assert campaign["cases"][1]["expected_model_runs"] == 3200
    assert campaign["expected_initial_model_runs"] == 4800


def test_convergence_not_yet_reached_return_code_can_be_recorded():
    assert _run(
        [sys.executable, "-c", "raise SystemExit(2)"],
        allowed_returncodes={0, 2},
    ) == 2
