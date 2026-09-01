import csv
from pathlib import Path

import pytest

from src.dssat import run_dssat


def _parameter_csv(path: Path, **values: float) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["name", "value"])
        writer.writerows(values.items())
    return path


def test_numeric_scom_does_not_shift_soil_scalar_injection(tmp_path, monkeypatch) -> None:
    source = Path(__file__).resolve().parents[1] / "data/raw/soil/SOIL.SOL"
    (tmp_path / "SOIL.SOL.base").write_bytes(source.read_bytes())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_dssat, "SOIL_BASE_FILE", "SOIL.SOL.base")
    monkeypatch.setattr(run_dssat, "SOIL_FILE", "SOIL.SOL")

    params = _parameter_csv(
        tmp_path / "soil_scalars.csv",
        SOIL_SALB=0.21,
        SOIL_SLDR=0.77,
        SOIL_SLRO=82.0,
        SOIL_SLNF=0.88,
        SOIL_SLPF=0.93,
    )
    run_dssat.update_soil_file(str(params), soil_id="IBTM910017")

    lines = (tmp_path / "SOIL.SOL").read_text(encoding="utf-8").splitlines()
    profile = next(i for i, line in enumerate(lines) if line.startswith("*IBTM910017"))
    header = next(i for i in range(profile, profile + 10) if "SCOM" in lines[i] and "SLPF" in lines[i])
    names = lines[header].split()[1:]
    row = dict(zip(names, lines[header + 1].split()))

    assert row["SCOM"] == "-99"
    assert float(row["SALB"]) == pytest.approx(0.21)
    assert float(row["SLDR"]) == pytest.approx(0.77)
    assert float(row["SLRO"]) == pytest.approx(82.0)
    assert float(row["SLNF"]) == pytest.approx(0.88)
    assert float(row["SLPF"]) == pytest.approx(0.93)
