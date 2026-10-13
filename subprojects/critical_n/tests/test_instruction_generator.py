"""Unit tests for PEST instruction file generation and PyEMU compatibility."""

from pathlib import Path
import pyemu
import pytest

from subprojects.critical_n.adapters.instruction_generator import (
    CNCObservationTarget,
    generate_pest_cnc_instructions,
    make_obs_name,
)
from subprojects.critical_n.adapters.pest_cnc_exporter import export_pest_cnc


def test_make_obs_name_format():
    """Verify observation name string formatting."""
    name = make_obs_name(treatment_id=3, das=65)
    assert name == "cnc_t3_d65"
    assert len(name) <= 20  # PEST standard 20 char limit


def test_generate_pest_cnc_instructions_pyemu_validation(tmp_path):
    """Verify generated PestCNC.ins is fully valid and parseable by PyEMU."""
    # Create synthetic run directory
    gro = tmp_path / "PlantGro.OUT"
    gro.write_text(
        "*RUN 1\n TREATMENT 1\n@YEAR DOY DAS CWAD\n"
        " 2025 075  8  10.0\n"
        " 2025 085 18 100.0\n"
        " 2025 100 33 500.0\n"
        " 2025 120 53 1500.0\n"
        " 2025 140 73 3000.0\n",
        encoding="utf-8",
    )
    n = tmp_path / "PlantN.OUT"
    n.write_text(
        "*RUN 1\n@YEAR DOY DAS CNAD\n"
        " 2025 075  8   0.4\n"
        " 2025 085 18   4.0\n"
        " 2025 100 33  20.0\n"
        " 2025 120 53  50.0\n"
        " 2025 140 73  95.0\n",
        encoding="utf-8",
    )

    targets = [
        CNCObservationTarget(obs_name="cnc_t1_d33", run_id=1, treatment_id=1, das=33, variable="NNI"),
        CNCObservationTarget(obs_name="cnc_t1_d73", run_id=1, treatment_id=1, das=73, variable="NNI"),
    ]

    ins_file = tmp_path / "PestCNC.OUT.ins"
    generate_pest_cnc_instructions(tmp_path, targets, ins_file)

    # PyEMU parse check
    obs_names = pyemu.pst_utils.parse_ins_file(str(ins_file))
    assert obs_names == ["cnc_t1_d33", "cnc_t1_d73"]

    # Test R_TOL column slice instruction generation
    targets_rtol = [
        CNCObservationTarget(obs_name="cnc_rtol_d33", run_id=1, treatment_id=1, das=33, variable="R_TOL"),
    ]
    ins_rtol_file = tmp_path / "PestCNC_rtol.ins"
    generate_pest_cnc_instructions(tmp_path, targets_rtol, ins_rtol_file)
    content_rtol = ins_rtol_file.read_text(encoding="utf-8")
    assert "[cnc_rtol_d33]65:74" in content_rtol
    obs_names_rtol = pyemu.pst_utils.parse_ins_file(str(ins_rtol_file))
    assert obs_names_rtol == ["cnc_rtol_d33"]


def test_pestpp_execution_and_extraction(tmp_path):
    """Verify that pestpp-ies executable executes and extracts exact NNI numbers via PestCNC.OUT.ins."""
    import os
    import subprocess
    import pandas as pd

    pestpp_exe = Path("pestpp-5.2.16-win/bin/pestpp-ies.exe").resolve()
    if not pestpp_exe.is_file():
        pytest.skip("pestpp-ies.exe not found")

    gro = tmp_path / "PlantGro.OUT"
    gro.write_text(
        "*RUN 1\n TREATMENT 1\n@YEAR DOY DAS CWAD\n"
        " 2025 100 33 1000.0\n"
        " 2025 120 53 2000.0\n",
        encoding="utf-8",
    )
    n = tmp_path / "PlantN.OUT"
    n.write_text(
        "*RUN 1\n@YEAR DOY DAS CNAD\n"
        " 2025 100 33  40.0\n"
        " 2025 120 53  60.0\n",
        encoding="utf-8",
    )

    export_pest_cnc(tmp_path)
    targets = [
        CNCObservationTarget(obs_name="cnc_t1_d33", run_id=1, treatment_id=1, das=33, variable="NNI"),
        CNCObservationTarget(obs_name="cnc_t1_d53", run_id=1, treatment_id=1, das=53, variable="NNI"),
    ]
    ins_file = tmp_path / "PestCNC.OUT.ins"
    generate_pest_cnc_instructions(tmp_path, targets, ins_file)

    # Build minimal Pst
    pst = pyemu.Pst.from_par_obs_names(["p1"], ["dummy_obs"])
    pst.parameter_data.loc["p1", "parval1"] = 1.0
    pst.parameter_data.loc["p1", "parlbnd"] = 0.5
    pst.parameter_data.loc["p1", "parubnd"] = 2.0
    pst.parameter_data.loc["p1", "partrans"] = "none"
    pst.observation_data.loc["dummy_obs", "obsval"] = 1.0
    pst.observation_data.loc["dummy_obs", "weight"] = 0.0

    (tmp_path / "dummy.tpl").write_text("ptf ~\n~ p1 ~\n")
    (tmp_path / "dummy.in").write_text("1.0\n")
    (tmp_path / "dummy.ins").write_text("pif ~\nl1 [dummy_obs]1:10\n")
    (tmp_path / "dummy.out").write_text(" 1.0000000\n")

    pst.model_input_data = pd.DataFrame([{"pest_file": "dummy.tpl", "model_file": "dummy.in"}])
    pst.model_output_data = pd.DataFrame([{"pest_file": "dummy.ins", "model_file": "dummy.out"}])

    from subprojects.critical_n.calibration.cnc_builder import attach_cnc_to_pst
    attach_cnc_to_pst(pst, targets, model_output_file="PestCNC.OUT", instruction_file="PestCNC.OUT.ins")

    run_py = tmp_path / "fwd.py"
    run_py.write_text(
        "from pathlib import Path\n"
        "Path('dummy.out').write_text(' 1.0\\n')\n"
        "from subprojects.critical_n.adapters.pest_cnc_exporter import export_pest_cnc\n"
        "export_pest_cnc('.')\n"
    )
    pst.model_command = "python fwd.py"
    pst.control_data.noptmax = 0

    pst_file = tmp_path / "test.pst"
    pst.write(str(pst_file))

    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(".").resolve())
    proc = subprocess.run([str(pestpp_exe), "test.pst"], cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0, f"pestpp-ies failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"

    obs_csv = tmp_path / "test.base.obs.csv"
    assert obs_csv.is_file()
    obs_df = pd.read_csv(obs_csv)
    assert "cnc_t1_d33" in obs_df.columns
    assert "cnc_t1_d53" in obs_df.columns
    # DAS 33: W=1.0 t/ha, Nc=4.85, N_act=4.0%, NNI=4.0/4.85=0.825
    assert obs_df["cnc_t1_d33"].iloc[0] == pytest.approx(4.0 / 4.85, rel=1e-2)


def test_pestpp_execution_and_extraction_relaxed_zero_residual(tmp_path):
    """End-to-end PEST++ ies execution verifying R_TOL extracts exact 0.000000 in tolerance interval."""
    import os
    import subprocess
    import pandas as pd
    from subprojects.critical_n.calibration.cnc_builder import attach_cnc_to_pst

    pestpp_exe = Path("pestpp-5.2.16-win/bin/pestpp-ies.exe").resolve()
    if not pestpp_exe.is_file():
        pytest.skip("pestpp-ies.exe not found")

    gro = tmp_path / "PlantGro.OUT"
    gro.write_text(
        "*RUN 1\n TREATMENT 1\n@YEAR DOY DAS CWAD\n"
        " 2025 100 33 1000.0\n",
        encoding="utf-8",
    )
    n = tmp_path / "PlantN.OUT"
    # CWAD = 1000 kg/ha (1.0 t/ha), CNAD = 53.35 kg/ha -> N_act = 5.335%
    # Nc = 4.85% -> NNI = 5.335 / 4.85 = 1.10 (inside N3 luxury [1.00, 1.30])
    n.write_text(
        "*RUN 1\n@YEAR DOY DAS CNAD\n"
        " 2025 100 33  53.35\n",
        encoding="utf-8",
    )

    targets = [
        CNCObservationTarget(
            obs_name="cnc_rtol_d33",
            run_id=1,
            treatment_id=1,
            das=33,
            variable="R_TOL",
            target_value=0.0,
            weight=1.0,
            group="cnc_nni",
        ),
    ]
    ins_file = tmp_path / "PestCNC.OUT.ins"
    generate_pest_cnc_instructions(tmp_path, targets, ins_file)

    # Minimal Pst
    pst = pyemu.Pst.from_par_obs_names(["p1"], ["dummy_obs"])
    pst.parameter_data.loc["p1", "parval1"] = 1.0
    pst.parameter_data.loc["p1", "parlbnd"] = 0.5
    pst.parameter_data.loc["p1", "parubnd"] = 2.0
    pst.parameter_data.loc["p1", "partrans"] = "none"
    pst.observation_data.loc["dummy_obs", "obsval"] = 1.0
    pst.observation_data.loc["dummy_obs", "weight"] = 0.0

    (tmp_path / "dummy.tpl").write_text("ptf ~\n~ p1 ~\n")
    (tmp_path / "dummy.in").write_text("1.0\n")
    (tmp_path / "dummy.ins").write_text("pif ~\nl1 [dummy_obs]1:10\n")
    (tmp_path / "dummy.out").write_text(" 1.0000000\n")

    pst.model_input_data = pd.DataFrame([{"pest_file": "dummy.tpl", "model_file": "dummy.in"}])
    pst.model_output_data = pd.DataFrame([{"pest_file": "dummy.ins", "model_file": "dummy.out"}])

    attach_cnc_to_pst(pst, targets, model_output_file="PestCNC.OUT", instruction_file="PestCNC.OUT.ins")

    run_py = tmp_path / "fwd.py"
    run_py.write_text(
        "from pathlib import Path\n"
        "Path('dummy.out').write_text(' 1.0\\n')\n"
        "from subprojects.critical_n.adapters.pest_cnc_exporter import export_pest_cnc\n"
        "export_pest_cnc('.', include_r_tol=True, treatment_n_levels={1: 'N3'})\n"
    )
    pst.model_command = "python fwd.py"
    pst.control_data.noptmax = 0

    pst_file = tmp_path / "test_relaxed.pst"
    pst.write(str(pst_file))

    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(".").resolve())
    proc = subprocess.run([str(pestpp_exe), "test_relaxed.pst"], cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0, f"pestpp-ies failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"

    obs_csv = tmp_path / "test_relaxed.base.obs.csv"
    assert obs_csv.is_file()
    obs_df = pd.read_csv(obs_csv)
    assert "cnc_rtol_d33" in obs_df.columns
    # Target value is 0.0, simulated R_TOL in [1.00, 1.30] evaluates to exact 0.000000!
    assert abs(obs_df["cnc_rtol_d33"].iloc[0]) < 1e-4
