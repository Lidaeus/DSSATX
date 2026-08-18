from pathlib import Path

from src.common.experiment_inputs import (
    filex_harvest_dates,
    management_alignment_findings,
)


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "data/user/ref/XXQL2501.TMX"
OPERATIONAL_FILEX = [
    ROOT / "data/raw/experiments/XXQL2501.TMX",
    ROOT / "data/user/experiments/XXQL2501/XXQL2501.TMX",
    ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729/XXQL2501.TMX",
    ROOT / "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801/XXQL2501.TMX",
    ROOT / "_seasons/25SP/XXQL2501.TMX",
    ROOT / "Workspace/XXQL2501.TMX",
]

OPERATIONAL_OBSERVATIONS = [
    ROOT / "data/raw/experiments/XXQL2501.TMT",
    ROOT / "data/user/experiments/XXQL2501/XXQL2501.TMT",
    ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729/XXQL2501.TMT",
    ROOT / "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801/XXQL2501.TMT",
    ROOT / "_seasons/25SP/XXQL2501.TMT",
    ROOT / "Workspace/XXQL2501.TMT",
]


def _data_rows(path: Path):
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        fields = line.split()
        if fields and fields[0].isdigit():
            yield fields


def test_operational_filex_management_matches_reference():
    reference_dates = filex_harvest_dates(REFERENCE)
    assert reference_dates[-1] == 25198
    for path in OPERATIONAL_FILEX:
        assert path.is_file()
        assert management_alignment_findings(path, REFERENCE) == []
        assert filex_harvest_dates(path) == reference_dates


def test_operational_filet_excludes_estimated_final_harvest():
    for path in OPERATIONAL_OBSERVATIONS:
        assert path.is_file()
        dates = [int(fields[1]) for fields in _data_rows(path)]
        assert dates
        assert max(dates) < 25203


def test_operational_filea_uses_last_real_harvest_and_no_estimated_yield():
    for path in [item.with_suffix(".TMA") for item in OPERATIONAL_OBSERVATIONS]:
        rows = list(_data_rows(path))
        assert rows
        assert max(int(fields[4]) for fields in rows) == 25198
        assert all(float(fields[5]) == -99 for fields in rows)
