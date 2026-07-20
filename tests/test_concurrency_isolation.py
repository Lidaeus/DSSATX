from __future__ import annotations

import sys
from pathlib import Path
import pytest
import subprocess

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.calibration import run_dssat as cal_rd


def test_prepare_run_directory_creates_correct_dssatpro(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cal_rd, "DATA_DIR", tmp_path / "data")
    
    templates = tmp_path / "data" / "templates"
    templates.mkdir(parents=True)
    (templates / "DSSATPRO.v48").write_text("CRD C:\\Original\\CRD\nTMD C:\\Original\\TMD\n", encoding="utf-8")
    (templates / "DSSAT48.INH").write_text("fake inh\n", encoding="utf-8")
    (templates / "DSSAT48.INP").write_text("fake inp\n", encoding="utf-8")
    
    genotype = templates / "genotype"
    genotype.mkdir()
    for filename in ("TMGRO048.CUL.base", "TMGRO048.ECO.base", "TMGRO048.SPE.base"):
        (genotype / filename).write_text("fake base\n", encoding="utf-8")
        
    soil = tmp_path / "data" / "raw" / "soil"
    soil.mkdir(parents=True)
    (soil / "SOIL.SOL").write_text("fake soil\n", encoding="utf-8")
    
    monkeypatch.setenv("DSSAT48_HOME", str(tmp_path / "dssat"))
    (tmp_path / "dssat").mkdir()
    (tmp_path / "dssat" / "DSCSM048.EXE").write_text("fake exe\n", encoding="utf-8")
    
    batch_dir = templates / "batch"
    batch_dir.mkdir(parents=True)
    (batch_dir / "DSSBatch.v48").write_text(
        "XXQL2501.TMX 1\nXXQL2502.TMX 1\n", encoding="utf-8"
    )
    
    exp_dir = tmp_path / "data" / "raw" / "experiments"
    exp_dir.mkdir(parents=True)
    (exp_dir / "XXQL2501.TMX").write_text("fake tmx\n", encoding="utf-8")
    (exp_dir / "XXQL2502.TMX").write_text("second fake tmx\n", encoding="utf-8")
    
    wth_dir = tmp_path / "data" / "raw" / "weather"
    wth_dir.mkdir(parents=True)
    (wth_dir / "XXLI2502.WTH").write_text("fake weather\n", encoding="utf-8")
    
    run_dir = tmp_path / "run_dir"
    cal_rd.prepare_run_directory(run_dir, ["--batch", "DSSBatch.v48"])
    
    dssatpro = run_dir / "DSSATPRO.v48"
    assert dssatpro.is_file()
    content = dssatpro.read_text(encoding="utf-8")
    
    expected_path_part = cal_rd._to_dssatpro_path(run_dir)
    assert f"CRD {expected_path_part}" in content
    assert f"TMD {expected_path_part}" in content
    assert (run_dir / "XXQL2501.TMX").is_file()
    assert (run_dir / "XXQL2502.TMX").is_file()


def test_main_appends_model_parameter(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["run_dssat.py", "--batch", "DSSBatch.v48"])
    monkeypatch.chdir(tmp_path)
    
    monkeypatch.setattr(cal_rd, "prepare_run_directory", lambda rd, args: Path("DSSBatch.v48"))
    monkeypatch.setattr(cal_rd, "_param_csv_name", lambda args: "pest_params.csv")
    
    called_args = []
    def mock_run(cmd, **kwargs):
        called_args.extend(cmd)
        class FakeResult:
            returncode = 0
        return FakeResult()
        
    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(cal_rd, "_atomic_copy_back", lambda r, p: None)
    
    cal_rd.main()
    
    assert "--model" in called_args
    model_idx = called_args.index("--model")
    assert called_args[model_idx + 1] == "CRGRO048"
