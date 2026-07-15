import csv
import os
from pathlib import Path
import time

import pytest

from src.calibration.run_dssat import prepare_run_directory
from src.dssat import run_dssat


ROOT = Path(__file__).resolve().parents[1]


def _parameter_csv(path: Path, **values: float) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["name", "value"])
        writer.writerows(values.items())
    return path


def test_candidate_validation_rejects_physical_and_relational_errors():
    with pytest.raises(ValueError, match="LFMAX"):
        run_dssat.validate_candidate_parameters({"LFMAX": 99.0})
    with pytest.raises(ValueError, match="TB1 < TO11"):
        run_dssat.validate_candidate_parameters(
            {"TB1": 10.0, "TO11": 30.0, "TO21": 25.0, "TM1": 40.0}
        )
    with pytest.raises(ValueError, match="SLLL < SDUL < SSAT"):
        run_dssat.validate_candidate_parameters(
            {"SOIL_SLLL_01": 0.30, "SOIL_SDUL_01": 0.20, "SOIL_SSAT_01": 0.40}
        )


def test_candidate_validation_accepts_shipped_tmgro_baselines():
    values = {
        "WTPSD": 0.004,
        "SD-PM": 400.0,
        "FL-LF": 400.0,
        "SDPDV": 111.4,
        "PARMAX": 41.0,
        "PHTMAX": 61.0,
        "FINREF": 220.0,
        "EVMODC": 0.0,
    }
    assert run_dssat.validate_candidate_parameters(values) == values


def test_fresh_output_guard_rejects_empty_and_stale_files(tmp_path):
    output = tmp_path / "Evaluate.OUT"
    output.write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError, match="empty"):
        run_dssat._assert_fresh_nonempty(output, time.time())

    output.write_text("old output", encoding="utf-8")
    old = time.time() - 30
    os.utime(output, (old, old))
    with pytest.raises(RuntimeError, match="stale"):
        run_dssat._assert_fresh_nonempty(output, time.time())


def test_cultivar_injection_changes_only_requested_parameter(tmp_path, monkeypatch):
    base = ROOT / "data" / "templates" / "genotype" / "TMGRO048.CUL.base"
    local_base = tmp_path / "TMGRO048.CUL.base"
    local_base.write_bytes(base.read_bytes())
    params = _parameter_csv(tmp_path / "params.csv", LFMAX=1.50)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_dssat, "CUL_BASE_FILE", local_base.name)
    monkeypatch.setattr(run_dssat, "CUL_FILE", "TMGRO048.CUL")

    run_dssat.update_cul_file(str(params), target_cultivar="TM0008")

    before = base.read_text(encoding="utf-8").splitlines()
    after = (tmp_path / "TMGRO048.CUL").read_text(encoding="utf-8").splitlines()
    changed = [(old, new) for old, new in zip(before, after) if old != new]
    assert len(changed) == 1
    assert changed[0][0].startswith("TM0008")
    assert "  1.50" in changed[0][1]


def test_ecotype_and_species_injection_use_local_base_files(tmp_path, monkeypatch):
    genotype = ROOT / "data" / "templates" / "genotype"
    for filename in ("TMGRO048.ECO", "TMGRO048.SPE"):
        (tmp_path / f"{filename}.base").write_bytes((genotype / f"{filename}.base").read_bytes())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_dssat, "ECO_FILE", "TMGRO048.ECO")
    monkeypatch.setattr(run_dssat, "SPE_FILE", "TMGRO048.SPE")

    eco_params = _parameter_csv(tmp_path / "eco.csv", XFINT=0.30)
    run_dssat.update_eco_file(str(eco_params), target_ecotype="TM0001")
    eco_line = next(
        line for line in (tmp_path / "TMGRO048.ECO").read_text(encoding="utf-8").splitlines()
        if line.startswith("TM0001")
    )
    assert eco_line.rstrip().endswith("0.30")

    spe_params = _parameter_csv(tmp_path / "spe.csv", KCAN=0.75)
    run_dssat.update_spe_file(str(spe_params))
    photosynthesis = next(
        line for line in (tmp_path / "TMGRO048.SPE").read_text(encoding="utf-8").splitlines()
        if "PARMAX,PHTMAX" in line
    )
    assert "0.75" in photosynthesis


def test_soil_and_initial_condition_injection_are_explicit(tmp_path, monkeypatch):
    soil_source = ROOT / "data" / "raw" / "soil" / "SOIL.SOL"
    (tmp_path / "SOIL.SOL.base").write_bytes(soil_source.read_bytes())
    experiment_source = ROOT / "data" / "raw" / "experiments" / "XXQL2501.TMX"
    experiment = tmp_path / "XXQL2501.TMX"
    experiment.write_bytes(experiment_source.read_bytes())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_dssat, "SOIL_BASE_FILE", "SOIL.SOL.base")
    monkeypatch.setattr(run_dssat, "SOIL_FILE", "SOIL.SOL")

    soil_params = _parameter_csv(
        tmp_path / "soil.csv",
        SOIL_SLLL_01=0.130,
        SOIL_SDUL_01=0.210,
        SOIL_SSAT_01=0.300,
    )
    run_dssat.update_soil_file(str(soil_params), soil_id="IBTM910017")
    soil_lines = (tmp_path / "SOIL.SOL").read_text(encoding="utf-8").splitlines()
    profile_index = next(i for i, line in enumerate(soil_lines) if line.startswith("*IBTM910017"))
    assert any("0.130 0.210 0.300" in line for line in soil_lines[profile_index : profile_index + 10])

    ic_params = _parameter_csv(tmp_path / "ic.csv", IC_SH2O_01=0.200)
    run_dssat.update_initial_conditions_file(str(ic_params), filex_path=str(experiment))
    ic_lines = experiment.read_text(encoding="utf-8").splitlines()
    header_index = next(i for i, line in enumerate(ic_lines) if "ICBL" in line and "SH2O" in line)
    assert ic_lines[header_index + 1].split()[2] == "0.200"


def test_run_directory_preparation_is_local_and_complete(tmp_path):
    batch = prepare_run_directory(tmp_path, ["--batch", "DSSBatch.v48"])
    required = {
        "TMGRO048.CUL.base",
        "TMGRO048.ECO.base",
        "TMGRO048.SPE.base",
        "SOIL.SOL.base",
        "DSSATPRO.v48",
        "DSCSM048.EXE",
        "DSSBatch.v48",
    }
    assert batch == tmp_path / "DSSBatch.v48"
    assert required.issubset({path.name for path in tmp_path.iterdir()})
    assert list(tmp_path.glob("*.TM?")), "experiment files must be localized"
    assert list(tmp_path.glob("*.WTH")), "weather files must be localized"
