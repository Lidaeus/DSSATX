import csv
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest
from src.dssat import run_dssat


def _parameter_csv(path: Path, **values: float) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["name", "value"])
        writer.writerows(values.items())
    return path


def test_seasonal_slpf_injection(tmp_path, monkeypatch) -> None:
    source = Path(__file__).resolve().parents[1] / "data/raw/soil/SOIL.SOL"
    (tmp_path / "SOIL.SOL.base").write_bytes(source.read_bytes())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_dssat, "SOIL_BASE_FILE", "SOIL.SOL.base")
    monkeypatch.setattr(run_dssat, "SOIL_FILE", "SOIL.SOL")

    params = _parameter_csv(
        tmp_path / "soil_scalars.csv",
        SLPF_25SP=0.95,
        SLPF_26SP=0.88,
    )
    run_dssat.update_soil_file(str(params), soil_id="IBTM910017")

    lines = (tmp_path / "SOIL.SOL").read_text(encoding="utf-8").splitlines()
    # Check 25SP profile
    p25 = next(i for i, line in enumerate(lines) if line.startswith("*IBTM910017"))
    h25 = next(i for i in range(p25, p25 + 10) if "SCOM" in lines[i] and "SLPF" in lines[i])
    row25 = lines[h25 + 1].split()
    tokens25 = lines[h25].split()[1:]
    dict25 = dict(zip(tokens25, row25))
    assert float(dict25["SLPF"]) == pytest.approx(0.95)

    # Check 26SP profile exists
    p26 = next(i for i, line in enumerate(lines) if line.startswith("*IB26910017"))
    h26 = next(i for i in range(p26, p26 + 10) if "SCOM" in lines[i] and "SLPF" in lines[i])
    row26 = lines[h26 + 1].split()
    tokens26 = lines[h26].split()[1:]
    dict26 = dict(zip(tokens26, row26))
    assert float(dict26["SLPF"]) == pytest.approx(0.88)
