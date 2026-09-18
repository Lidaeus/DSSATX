from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from src.reporting.ies_plot_provenance import load_ies_plot_sources
from tools.experiments.sync_26sp_lai_bundles_20260902 import patch_tmt, patch_filet


def ies_fixture(tmp_path):
    (tmp_path / "case.pst").write_text("pcf\n* parameter data\nx none relative 1 0 2 gp 1 0 1\n* observation groups\n")
    for it in (0, 10):
        pd.DataFrame({"real_name": ["0", "1"], "x": [.5, 1.5]}).to_csv(tmp_path / f"case.{it}.par.csv", index=False)
    pd.DataFrame({"iteration": [0, 10], "total_runs": [2, 4], "mean": [1., .5], "0": [1., .5], "1": [1., .5]}).to_csv(tmp_path / "case.phi.actual.csv", index=False)


def test_explicit_iteration_and_no_prior_fallback(tmp_path):
    ies_fixture(tmp_path)
    prior, post, evidence = load_ies_plot_sources(tmp_path, "case", 10)
    assert len(prior) == len(post) == 2 and evidence["iteration"] == 10
    (tmp_path / "case.0.par.csv").unlink()
    with pytest.raises(ValueError, match="prior"):
        load_ies_plot_sources(tmp_path, "case", 10)


def test_other_run_prior_and_bounds_rejected(tmp_path):
    ies_fixture(tmp_path)
    with pytest.raises(ValueError, match="prior"):
        load_ies_plot_sources(tmp_path, "case", 10, prior=tmp_path / "other.0.par.csv")
    pd.DataFrame({"real_name": ["0", "1"], "x": [9., 1.]}).to_csv(tmp_path / "case.10.par.csv", index=False)
    with pytest.raises(ValueError, match="bounds"):
        load_ies_plot_sources(tmp_path, "case", 10)


def test_summary_phi_cannot_establish_ies_source(tmp_path):
    ies_fixture(tmp_path)
    (tmp_path / "case.phi.actual.csv").write_text("iteration,real_name,phi\n0,0,2000\n10,0,1000\n")
    with pytest.raises(ValueError, match="original IES"):
        load_ies_plot_sources(tmp_path, "case", 10)


def test_lai_only_replaces_target_field_and_keeps_harvest():
    values = {1: {"value": "2.646"}}
    raw = b"     1 26180   -99   -99  1456   -99 1.234\r\n"
    result = patch_tmt(raw, values)
    assert result[:18] == raw[:18] and result[24:] == raw[24:]
    assert float(result[18:24]) == 2.646
    csv_raw = b"TRNO,DATE,LAID,LWAD,CHFPW,PDMCD\r\n1,2026-06-29,,1456,12345.6789,4.91\r\n"
    patched = patch_filet(csv_raw, values)
    assert patched == csv_raw.replace(b"06-29,,", b"06-29,2.646,")
    with pytest.raises(ValueError, match="Conflicting"):
        patch_filet(csv_raw.replace(b"06-29,,", b"06-29,9,"), values)


def test_posterior_autoselection_is_numeric_and_never_prior(tmp_path):
    from src.reporting.equifinality import _read_latest_par_iteration
    for it in (0, 9, 10):
        pd.DataFrame({"real_name": ["0"], "x": [it]}).to_csv(tmp_path / f"case.{it}.par.csv", index=False)
    assert _read_latest_par_iteration(tmp_path, "case").X.iloc[0] == 10
    (tmp_path / "case.9.par.csv").unlink()
    (tmp_path / "case.10.par.csv").unlink()
    with pytest.raises(FileNotFoundError, match="no IES posterior"):
        _read_latest_par_iteration(tmp_path, "case")
