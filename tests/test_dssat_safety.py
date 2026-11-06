import csv
import os
import re
from pathlib import Path
import time

import pytest

from src.calibration.run_dssat import prepare_run_directory
from src.dssat import run_dssat
from src.dssat.array_expander import (
    expand_leaf_area,
    expand_leaf_partition,
    expand_senpor,
    expand_stem_partition,
)


ROOT = Path(__file__).resolve().parents[1]


def _parameter_csv(path: Path, **values: float) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["name", "value"])
        writer.writerows(values.items())
    return path


def test_candidate_validation_logs_safety_and_relation_risks_without_freezing(capsys):
    values = {
        "LFMAX": 99.0,
        "TB1": 10.0,
        "TO11": 30.0,
        "TO21": 25.0,
        "TM1": 40.0,
        "SOIL_SLLL_01": 0.30,
        "SOIL_SDUL_01": 0.20,
        "SOIL_SSAT_01": 0.40,
    }
    assert run_dssat.validate_candidate_parameters(values) == values
    captured = capsys.readouterr()
    assert "RUNNER_ADVISORY parameter=LFMAX" in captured.err
    assert "RUNNER_ADVISORY relation=TB1<TO11<TO21<TM1" in captured.err
    assert "RUNNER_ADVISORY relation=SOIL_SLLL_01<SOIL_SDUL_01<SOIL_SSAT_01" in captured.err


def test_candidate_validation_still_rejects_nonfinite_values():
    with pytest.raises(ValueError, match="must be finite"):
        run_dssat.validate_candidate_parameters({"LFMAX": float("nan")})


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


def test_candidate_validation_accepts_reviewed_indeterminate_and_partition_values():
    values = {
        "FL-VS": 120.0,
        "XMAGE": 30.0,
        "XFPHT": 60.0,
        "XFINT": 0.10,
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
    assert abs(float(eco_line.split()[-1]) - 0.30) < 1e-9  # T2: numeric equivalence (injected ".3" is value-correct fixed-width)

    spe_params = _parameter_csv(tmp_path / "spe.csv", KCAN=0.75)
    run_dssat.update_spe_file(str(spe_params))
    photosynthesis = next(
        line for line in (tmp_path / "TMGRO048.SPE").read_text(encoding="utf-8").splitlines()
        if "PARMAX,PHTMAX" in line
    )
    assert abs(float(photosynthesis.split()[2]) - 0.75) < 1e-9  # T2: numeric equivalence


def test_species_injection_updates_fruit_water_related_spe_fields(tmp_path, monkeypatch):
    genotype = ROOT / "data" / "templates" / "genotype"
    (tmp_path / "TMGRO048.SPE.base").write_bytes((genotype / "TMGRO048.SPE.base").read_bytes())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_dssat, "SPE_FILE", "TMGRO048.SPE")

    spe_params = _parameter_csv(
        tmp_path / "spe_fwc.csv",
        SDPROS=0.410,
        PCARSD=0.620,
        XMPAGE=120.0,
    )
    run_dssat.update_spe_file(str(spe_params))
    lines = (tmp_path / "TMGRO048.SPE").read_text(encoding="utf-8").splitlines()

    composition = next(line for line in lines if "SDPROS,SDPROG" in line)
    assert abs(float(composition.split()[0]) - 0.410) < 1e-9  # T2: numeric equivalence

    carbohydrate = next(line for line in lines if "PCARLF,PCARST" in line)
    assert abs(float(carbohydrate.split()[0]) - 0.620) < 1e-9  # T2: numeric equivalence

    seed_shell = next(line for line in lines if "SETMAX,SRMAX" in line)
    assert "120" in seed_shell


def test_species_injection_expands_anchor_parameters_into_spe_arrays(tmp_path, monkeypatch):
    genotype = ROOT / "data" / "templates" / "genotype"
    (tmp_path / "TMGRO048.SPE.base").write_bytes((genotype / "TMGRO048.SPE.base").read_bytes())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_dssat, "SPE_FILE", "TMGRO048.SPE")

    spe_params = _parameter_csv(
        tmp_path / "spe_anchor.csv",
        LAREA_EARLY=18.0,
        LAREA_MID=220.0,
        LAREA_LATE=510.0,
        LEAF_PART_EARLY=0.32,
        LEAF_PART_FLORAL=0.55,
        LEAF_PART_LATE=0.28,
        STEM_PART_EARLY=0.22,
        STEM_PART_LATE=0.50,
        SENPOR_LATE=0.30,
    )
    run_dssat.update_spe_file(str(spe_params))
    lines = (tmp_path / "TMGRO048.SPE").read_text(encoding="utf-8").splitlines()

    def first_numbers(line: str, count: int) -> list[float]:
        return [float(m.group(0)) for m in re.finditer(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[Ee][-+]?\d+)?", line)][:count]

    yvref_line = next(line for line in lines if "YVREF(1-6)" in line)
    assert first_numbers(yvref_line, 6) == pytest.approx(
        expand_leaf_area(18.0, 220.0, 510.0).y_values,
        abs=0.5,
    )

    yleaf_line = next(line for line in lines if "YLEAF VALUES" in line)
    assert first_numbers(yleaf_line, 10) == pytest.approx(
        expand_leaf_partition(0.32, 0.55, 0.28).y_values,
        abs=0.02,
    )

    ystem_line = next(line for line in lines if "YSTEM VALUES" in line)
    assert first_numbers(ystem_line, 10) == pytest.approx(
        expand_stem_partition(0.22, 0.50).y_values,
        abs=0.02,
    )

    senpor_idx = next(i for i, line in enumerate(lines) if "SENPOR........." in line)
    assert first_numbers(lines[senpor_idx + 1], 4) == pytest.approx(
        expand_senpor(0.30).y_values,
        abs=0.02,
    )


def test_xfint_historical_safety_threshold_is_advisory_not_a_runner_rejection(tmp_path, monkeypatch, capsys):
    """T10-approved XFINT=0.08 must reach DSSAT after an auditable warning."""
    genotype = ROOT / "data" / "templates" / "genotype"
    (tmp_path / "TMGRO048.ECO.base").write_bytes((genotype / "TMGRO048.ECO.base").read_bytes())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_dssat, "ECO_FILE", "TMGRO048.ECO")

    eco_params = _parameter_csv(tmp_path / "eco_xfint_008.csv", XFINT=0.08)
    run_dssat.update_eco_file(str(eco_params), target_ecotype="TM0001")

    captured = capsys.readouterr()
    assert "RUNNER_ADVISORY parameter=XFINT value=0.08" in captured.err
    eco_line = next(
        line for line in (tmp_path / "TMGRO048.ECO").read_text(encoding="utf-8").splitlines()
        if line.startswith("TM0001")
    )
    assert abs(float(eco_line.split()[-1]) - 0.08) < 1e-9  # T2: numeric equivalence


def _is_float(v):
    try:
        float(v)
        return True
    except ValueError:
        return False


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
    run_dssat.update_soil_file(str(soil_params), soil_id="XXSL2501")
    soil_lines = (tmp_path / "SOIL.SOL").read_text(encoding="utf-8").splitlines()
    profile_index = next(i for i, line in enumerate(soil_lines) if line.startswith("*XXSL2501"))
    assert any(  # T2: numeric equivalence (injected fields use leading-zero-free fixed width)
        any(
            abs(float(vals[k]) - 0.130) < 1e-9
            and abs(float(vals[k + 1]) - 0.210) < 1e-9
            and abs(float(vals[k + 2]) - 0.300) < 1e-9
            for k in range(len(vals) - 2)
        )
        for line in soil_lines[profile_index : profile_index + 10]
        if (vals := [v for v in line.split() if _is_float(v)])
    )

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


def test_run_directory_uses_explicit_user_bundle_without_raw_fallback(tmp_path):
    bundle = ROOT / "data" / "user" / "experiments" / "xxql2501_final_20261105"
    batch = prepare_run_directory(
        tmp_path,
        ["--input-dir", str(bundle), "--batch", "DSSBatch.v48"],
    )
    assert batch == tmp_path / "DSSBatch.v48"
    for name in ("XXQL2501.TMX", "XXQL2501.TMA", "XXQL2501.TMT", "XXTW2403.WTH"):
        assert (tmp_path / name).read_bytes() == (bundle / name).read_bytes()
    assert (tmp_path / "SOIL.SOL.base").read_bytes() == (bundle / "SOIL.SOL").read_bytes()


def test_atomic_copy_back_publishes_raw_dssat_outputs_for_sa(tmp_path):
    """The SA pipeline (sa_model.py) reads raw PlantGro.OUT/FreshWt.OUT/
    Evaluate.OUT daily trajectories to build the 164-response contract; the
    summary Pest*.OUT do not carry them. _atomic_copy_back must therefore copy
    the raw outputs back from the ephemeral iso dir alongside the PEST
    interface files, or every SA output silently becomes the -99 sentinel.
    """
    from src.calibration.run_dssat import _RAW_DSSAT_OUTPUT_FILES, _atomic_copy_back

    source = tmp_path / "iso_run"
    source.mkdir()
    dest = tmp_path / "pest_dir"
    dest.mkdir()
    # Simulate the files a real DSSAT run leaves in the iso dir.
    for name in ("PestEval.OUT", "PestTmtGrow.OUT", "Evaluate.OUT", "PlantGro.OUT", "FreshWt.OUT"):
        (source / name).write_text(f"{name} content\n", encoding="utf-8")

    _atomic_copy_back(source, dest)

    # PEST interface files are copied back.
    assert (dest / "PestEval.OUT").read_text() == "PestEval.OUT content\n"
    # Raw DSSAT outputs the SA contract depends on are copied back too.
    for name in _RAW_DSSAT_OUTPUT_FILES:
        assert (dest / name).is_file(), f"{name} must be published for SA consumption"
        assert (dest / name).read_text() == f"{name} content\n"
