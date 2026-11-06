#!/usr/bin/env python3
"""
Independent Adversarial Consistency and Stress-Test Harness for Champion Candidate C31.

This test suite is executed by challenger_10_1 to independently and adversarially
verify:
1. Exact parameter alignment between Table 1 and C31 params.csv (168 parameters).
2. Water response ladder monotonicity in Table 4 (W2 > W1 and W3 > W1 for all spring treatments).
3. Nitrogen response consistency in Table 3.
4. Numerical parity across manuscript sections, compiled report, CSV tables, and candidate manifest.
5. Complete absence of obsolete candidate tokens ('C23', 'C16', '8.4656') in active manuscript files.
6. Figure manifest SHA-256 integrity across all 224 figure artifacts and 7 paper data bundles.
"""

import sys
import json
import re
import hashlib
from pathlib import Path
import pandas as pd
import numpy as np
import pytest

PROJECT_ROOT = Path("D:/Tomato_Cal")
CAND_DIR = PROJECT_ROOT / "workspace/candidates/candidate_c31_scheme1_dual_spring_precision"
TABLES_DIR = PROJECT_ROOT / "paper/02_Tables"
SECTIONS_DIR = PROJECT_ROOT / "paper/01_Sections"
FIGURES_DIR = PROJECT_ROOT / "paper/03_Figures"
PAPER_DATA_DIR = PROJECT_ROOT / "paper/paper_data"
CONFIGS_DIR = PROJECT_ROOT / "configs/figures"


def test_parameter_alignment_168_exact():
    """Verify all 168 parameters in Table 1 match C31 params.csv with 0.0 discrepancy."""
    t1_path = TABLES_DIR / "Table1_Genetic_Parameters_Comparison.csv"
    p_path = CAND_DIR / "params.csv"
    assert t1_path.exists(), f"Missing {t1_path}"
    assert p_path.exists(), f"Missing {p_path}"

    df1 = pd.read_csv(t1_path)
    df_p = pd.read_csv(p_path)

    assert len(df1) == 168, f"Table 1 row count mismatch: expected 168, got {len(df1)}"
    assert len(df_p) == 168, f"params.csv row count mismatch: expected 168, got {len(df_p)}"

    dict_t1 = dict(zip(df1["name"].str.lower(), df1["c31_value"]))
    dict_p = dict(zip(df_p["name"].str.lower(), df_p["value"]))

    assert set(dict_t1.keys()) == set(dict_p.keys()), "Parameter name sets differ!"

    max_diff = 0.0
    for k in dict_t1:
        v1 = dict_t1[k]
        v2 = dict_p[k]
        diff = abs(v1 - v2)
        if diff > max_diff:
            max_diff = diff
        assert diff < 1e-6, f"Parameter mismatch for {k}: Table1={v1}, params.csv={v2}"

    assert max_diff == 0.0, f"Max param difference should be 0.0, got {max_diff}"

    # Verify TB1 explicitly
    assert abs(dict_t1["tb1"] - 9.20) < 1e-6, f"TB1 is {dict_t1['tb1']}, expected 9.20"

    # Verify physiological nitrogen hierarchy
    fnpgn1 = dict_t1["fnpgn1"]
    fnpgn2 = dict_t1["fnpgn2"]
    lnref = dict_t1["lnref"]
    fnpgn3 = dict_t1["fnpgn3"]
    fnpgn4 = dict_t1["fnpgn4"]
    assert fnpgn1 < fnpgn2 <= lnref <= fnpgn3 <= fnpgn4, (
        f"Nitrogen hierarchy contract violated: {fnpgn1} < {fnpgn2} <= {lnref} <= {fnpgn3} <= {fnpgn4}"
    )

    # Verify key parameters against candidate_manifest.json
    manifest_path = CAND_DIR / "candidate_manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    kp = manifest["key_parameters"]
    assert abs(dict_t1["tb1"] - kp["tb1"]) < 1e-6
    assert abs(dict_t1["kcan"] - kp["kcan"]) < 1e-6
    assert abs(dict_t1["sizlf"] - kp["sizlf"]) < 1e-4
    assert abs(dict_t1["dswbar"] - kp["dswbar"]) < 1e-4
    assert abs(dict_t1["fl-sd"] - kp["fl-sd"]) < 1e-4
    assert abs(dict_t1["podur"] - kp["podur"]) < 1e-4
    assert abs(dict_t1["lngsh"] - kp["lngsh"]) < 1e-4
    assert abs(dict_t1["slpf_25sp"] - kp["slpf_25sp"]) < 1e-6
    assert abs(dict_t1["slpf_26sp"] - kp["slpf_26sp"]) < 1e-6
    assert abs(dict_t1["sasc_ratio"] - kp["sasc_ratio"]) < 1e-6


def test_water_response_ladders_monotonicity():
    """Adversarially test Table 4 water response ladders to ensure W2 > W1 and W3 > W1 in all spring treatments."""
    t4_path = TABLES_DIR / "Table4_Water_Response_Gaps.csv"
    assert t4_path.exists(), f"Missing {t4_path}"
    df4 = pd.read_csv(t4_path)

    # Recompute independently from all_35_treatments_final_yield.csv
    raw_yield = pd.read_csv(CAND_DIR / "all_35_treatments_final_yield.csv")
    raw_yield["water"] = raw_yield["treatment_label"].str.extract(r"(W[1-3]|CK)")
    raw_yield["nitrogen"] = raw_yield["treatment_label"].str.extract(r"(N[0-3])")

    for _, row in df4.iterrows():
        s = row["season"]
        n = row["nitrogen"]
        contrast = row["contrast"]
        w_hi, w_lo = contrast.split("-")
        y_hi = raw_yield[(raw_yield["season"] == s) & (raw_yield["nitrogen"] == n) & (raw_yield["water"] == w_hi)].iloc[0]
        y_lo = raw_yield[(raw_yield["season"] == s) & (raw_yield["nitrogen"] == n) & (raw_yield["water"] == w_lo)].iloc[0]

        expected_obs_gap = y_hi["obs_t_ha"] - y_lo["obs_t_ha"]
        expected_sim_gap = y_hi["sim_t_ha"] - y_lo["sim_t_ha"]

        assert abs(row["observed_gap"] - expected_obs_gap) < 1e-4, f"Mismatch in obs gap for {s} {n} {contrast}"
        assert abs(row["simulated_gap"] - expected_sim_gap) < 1e-4, f"Mismatch in sim gap for {s} {n} {contrast}"

    # Filter spring treatments (25SP and 26SP)
    spring_df = df4[df4["season"].isin(["25SP", "26SP"])]
    assert len(spring_df) == 14, f"Expected 14 spring water gap rows, found {len(spring_df)}"

    # ADVERSARIAL STRESS TEST: strictly positive simulated gaps
    for _, row in spring_df.iterrows():
        s = row["season"]
        n = row["nitrogen"]
        c = row["contrast"]
        sim_gap = row["simulated_gap"]
        # Must be strictly positive
        assert sim_gap > 0.0, f"VIOLATION: Non-positive water response in spring: {s} {n} {c} = {sim_gap}"
        # Adversarial check: verify at least 2.0 t/ha
        assert sim_gap >= 2.0, f"Suspiciously low water response in spring: {s} {n} {c} = {sim_gap}"

    # Check zero-N unphysical irrigation leaching resolution
    sp25_n0_w3w1 = df4[(df4["season"] == "25SP") & (df4["nitrogen"] == "N0") & (df4["contrast"] == "W3-W1")].iloc[0]["simulated_gap"]
    sp26_n0_w3w1 = df4[(df4["season"] == "26SP") & (df4["nitrogen"] == "N0") & (df4["contrast"] == "W3-W1")].iloc[0]["simulated_gap"]
    assert abs(sp25_n0_w3w1 - 13.2586) < 1e-3, f"25SP N0 W3-W1 mismatch: {sp25_n0_w3w1}"
    assert abs(sp26_n0_w3w1 - 2.5433) < 1e-3, f"26SP N0 W3-W1 mismatch: {sp26_n0_w3w1}"
    assert sp25_n0_w3w1 > 0.0
    assert sp26_n0_w3w1 > 0.0


def test_nitrogen_response_ladders_consistency():
    """Adversarially test Table 3 nitrogen response consistency and recovery rates."""
    t3_path = TABLES_DIR / "Table3_Water_Nitrogen_Response_Gaps.csv"
    assert t3_path.exists(), f"Missing {t3_path}"
    df3 = pd.read_csv(t3_path)

    raw_yield = pd.read_csv(CAND_DIR / "all_35_treatments_final_yield.csv")
    raw_yield["water"] = raw_yield["treatment_label"].str.extract(r"(W[1-3]|CK)")
    raw_yield["nitrogen"] = raw_yield["treatment_label"].str.extract(r"(N[0-3])")

    for _, row in df3.iterrows():
        s = row["season"]
        w = row["water"]
        contrast = row["contrast"]
        n_hi, n_lo = contrast.split("-")
        y_hi = raw_yield[(raw_yield["season"] == s) & (raw_yield["water"] == w) & (raw_yield["nitrogen"] == n_hi)].iloc[0]
        y_lo = raw_yield[(raw_yield["season"] == s) & (raw_yield["water"] == w) & (raw_yield["nitrogen"] == n_lo)].iloc[0]

        expected_obs_gap = y_hi["obs_t_ha"] - y_lo["obs_t_ha"]
        expected_sim_gap = y_hi["sim_t_ha"] - y_lo["sim_t_ha"]

        assert abs(row["observed_gap"] - expected_obs_gap) < 1e-4, f"Mismatch in obs gap for {s} {w} {contrast}"
        assert abs(row["c31_simulated_gap"] - expected_sim_gap) < 1e-4, f"Mismatch in sim gap for {s} {w} {contrast}"
        if expected_obs_gap != 0:
            rec = (expected_sim_gap / expected_obs_gap) * 100.0
            assert abs(row["recovery_pct"] - rec) < 1e-4

    # In spring, all N3-N0 gaps must be positive and substantial (> 7 t/ha)
    spring_n3n0 = df3[(df3["season"].isin(["25SP", "26SP"])) & (df3["contrast"] == "N3-N0")]
    assert len(spring_n3n0) == 6, f"Expected 6 spring N3-N0 combinations, got {len(spring_n3n0)}"
    for _, row in spring_n3n0.iterrows():
        assert row["c31_simulated_gap"] > 7.0, (
            f"Spring N3-N0 gap {row['season']} {row['water']} unexpectedly low: {row['c31_simulated_gap']}"
        )


def test_number_parity_across_manuscript_tables_manifest():
    """Extract and cross-verify all numeric performance metrics across manifest, Table 2, report, and sections."""
    t2_path = TABLES_DIR / "Table2_Model_Statistical_Performance_Yield.csv"
    assert t2_path.exists(), f"Missing {t2_path}"
    df2 = pd.read_csv(t2_path).set_index("group")

    manifest_path = CAND_DIR / "candidate_manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    m = manifest["metrics"]

    # 1. Parity between manifest metrics and Table 2 CSV
    # 26SP
    row26 = df2.loc["26SP"]
    m26 = m["26sp_12trt"]
    assert abs(row26["r_squared"] - m26["r2"]) < 1e-5
    assert abs(row26["nrmse_pct"] - m26["nrmse_pct"]) < 1e-5
    assert abs(row26["nse"] - m26["nse"]) < 1e-5
    assert abs(row26["d_index"] - m26["d_index"]) < 1e-5
    assert abs(row26["rmse"] - m26["rmse_t_ha"]) < 1e-5
    assert abs(row26["bias"] - m26["bias_t_ha"]) < 1e-5

    # 25SP
    row25 = df2.loc["25SP"]
    m25 = m["25sp_11trt"]
    assert abs(row25["r_squared"] - m25["r2"]) < 1e-5
    assert abs(row25["nrmse_pct"] - m25["nrmse_pct"]) < 1e-5
    assert abs(row25["nse"] - m25["nse"]) < 1e-5
    assert abs(row25["d_index"] - m25["d_index"]) < 1e-5

    # Two Springs
    row2s = df2.loc["two_springs"]
    m2s = m["twospring_23trt"]
    assert abs(row2s["r_squared"] - m2s["r2"]) < 1e-5
    assert abs(row2s["nrmse_pct"] - m2s["nrmse_pct"]) < 1e-5
    assert abs(row2s["nse"] - m2s["nse"]) < 1e-5
    assert abs(row2s["d_index"] - m2s["d_index"]) < 1e-5

    # Grand 35
    row35 = df2.loc["all_35"]
    m35 = m["grand_35trt"]
    assert abs(row35["r_squared"] - m35["r2"]) < 1e-5
    assert abs(row35["nrmse_pct"] - m35["nrmse_pct"]) < 1e-5
    assert abs(row35["nse"] - m35["nse"]) < 1e-5
    assert abs(row35["d_index"] - m35["d_index"]) < 1e-5

    # 25FA
    rowfa = df2.loc["25FA"]
    mfa = m["25fa_12trt"]
    assert abs(rowfa["nrmse_pct"] - mfa["nrmse_pct"]) < 1e-5
    assert abs(rowfa["rmse"] - mfa["rmse_t_ha"]) < 1e-5

    # 2. Check Tables_Compiled_Report.md
    report_text = (TABLES_DIR / "Tables_Compiled_Report.md").read_text(encoding="utf-8")
    assert "0.702" in report_text or "0.7016" in report_text
    assert "4.89" in report_text
    assert "+0.701" in report_text
    assert "0.880" in report_text
    assert "6.24" in report_text
    assert "0.725" in report_text
    assert "5.57" in report_text
    assert "0.984" in report_text
    assert "7.67" in report_text
    assert "13.41" in report_text
    assert "23.07" in report_text

    # 3. Check Active Manuscript Sections
    sections = [
        SECTIONS_DIR / "03_Results_Section.md",
        SECTIONS_DIR / "04_Discussion_Section.md",
        SECTIONS_DIR / "00_Combined_Results_Discussion.md",
    ]
    for s_path in sections:
        assert s_path.exists(), f"Missing manuscript: {s_path}"
        stext = s_path.read_text(encoding="utf-8")
        assert "0.7016" in stext, f"0.7016 missing in {s_path.name}"
        assert "4.89%" in stext or "4.89" in stext, f"4.89% missing in {s_path.name}"
        assert "+0.7011" in stext or "0.7011" in stext, f"+0.7011 missing in {s_path.name}"
        assert "0.8802" in stext, f"0.8802 missing in {s_path.name}"
        assert "6.24%" in stext or "6.24" in stext, f"6.24% missing in {s_path.name}"
        assert "0.7246" in stext, f"0.7246 missing in {s_path.name}"
        assert "5.57%" in stext or "5.57" in stext, f"5.57% missing in {s_path.name}"
        assert "7.67%" in stext or "7.67" in stext, f"7.67% missing in {s_path.name}"
        assert "13.41" in stext, f"13.41 missing in {s_path.name}"
        assert "23.07%" in stext or "23.07" in stext, f"23.07% missing in {s_path.name}"
        assert "TB1 = 9.20" in stext or "TB1=9.20" in stext or "9.20 °C" in stext or "9.20°C" in stext, (
            f"TB1=9.20 missing in {s_path.name}"
        )


def test_search_lingering_stale_tokens():
    """Adversarially search for old candidate tokens in active manuscript files and verify obsolete dir removal."""
    # Obsolete folders and files must be absent
    obsolete_paths = [
        PROJECT_ROOT / "paper/06_C16_Revision_20260920",
        PROJECT_ROOT / "paper/07_C23_Revision_20260922",
        PROJECT_ROOT / "paper/02_Tables/C16",
        PROJECT_ROOT / "paper/02_Tables/C23",
        PROJECT_ROOT / "paper/01_Sections/03_Results_Section_C23.md",
        PROJECT_ROOT / "paper/01_Sections/04_Discussion_Section_C23.md",
        PROJECT_ROOT / "paper/03_Figures/README_C16.md",
        PROJECT_ROOT / "paper/03_Figures/README_C23.md",
    ]
    for p in obsolete_paths:
        assert not p.exists(), f"Obsolete path still present: {p}"

    # Search active manuscript files for stale tokens
    manuscript_files = [
        SECTIONS_DIR / "03_Results_Section.md",
        SECTIONS_DIR / "04_Discussion_Section.md",
        SECTIONS_DIR / "00_Combined_Results_Discussion.md",
        TABLES_DIR / "Tables_Compiled_Report.md",
    ]

    stale_patterns = [
        r"8\.4656",
        r"Champion\s+C23",
        r"Champion\s+C16",
        r"candidate_c23",
        r"candidate_c16",
        r"c23_",
        r"c16_",
    ]

    for mfile in manuscript_files:
        assert mfile.exists(), f"Missing {mfile}"
        content = mfile.read_text(encoding="utf-8")
        for pat in stale_patterns:
            matches = re.findall(pat, content, flags=re.IGNORECASE)
            assert not matches, f"Found stale pattern '{pat}' in {mfile.name}: {matches}"


def test_figure_manifest_sha256_integrity():
    """Verify SHA-256 for all 224 figure artifacts and all 7 paper data bundles."""
    fig_manifest_path = FIGURES_DIR / "figure_manifest.json"
    assert fig_manifest_path.exists(), f"Missing {fig_manifest_path}"
    with open(fig_manifest_path, "r", encoding="utf-8") as f:
        fig_data = json.load(f)

    artifacts = fig_data["artifacts"]
    assert len(artifacts) == 224, f"Expected 224 artifacts in figure_manifest.json, got {len(artifacts)}"

    for art in artifacts:
        art_path = FIGURES_DIR / art["path"]
        assert art_path.exists(), f"Missing figure artifact: {art_path}"
        sha = hashlib.sha256(art_path.read_bytes()).hexdigest()
        assert sha == art["sha256"], f"SHA mismatch on {art['path']}: expected {art['sha256']}, got {sha}"

    # Verify all 7 data bundles
    bundles = ["25SP", "26SP", "25FA", "terminal", "leaf_n", "ensemble", "conditional"]
    total_bundle_files = 0
    for b in bundles:
        b_manifest = PAPER_DATA_DIR / b / "paper_data_manifest.json"
        assert b_manifest.exists(), f"Missing paper data manifest for bundle {b}"
        with open(b_manifest, "r", encoding="utf-8") as f:
            b_data = json.load(f)
        artifacts = b_data.get("artifacts", [])
        assert len(artifacts) > 0, f"No artifacts in bundle {b}"
        for art in artifacts:
            rel_p = art["path"]
            exp_sha = art["sha256"]
            fpath = PAPER_DATA_DIR / b / rel_p
            assert fpath.exists(), f"Missing bundle file {fpath}"
            sha = hashlib.sha256(fpath.read_bytes()).hexdigest()
            assert sha == exp_sha, f"SHA mismatch in bundle {b} on {rel_p}"
            total_bundle_files += 1

    assert total_bundle_files >= 25, f"Expected >= 25 bundle files, verified {total_bundle_files}"


def test_individual_yield_records_consistency():
    """Verify all 35 individual yield records in all_35_treatments_final_yield.csv."""
    yield_csv = CAND_DIR / "all_35_treatments_final_yield.csv"
    assert yield_csv.exists(), f"Missing {yield_csv}"
    df = pd.read_csv(yield_csv)
    assert len(df) == 35, f"Expected 35 treatment records, got {len(df)}"

    for _, r in df.iterrows():
        assert r["candidate"] == "C31"
        assert r["obs_t_ha"] > 0.0
        assert r["sim_t_ha"] > 0.0
        err = r["sim_t_ha"] - r["obs_t_ha"]
        assert abs(r["err_t_ha"] - err) < 1e-4
        rel_err = (err / r["obs_t_ha"]) * 100.0
        assert abs(r["rel_err_pct"] - rel_err) < 1e-4


def test_table4_summary_statistics_exact():
    """Verify exact calculation of Table 4 summary rows (n, mean, RMSE, MAE)."""
    df4 = pd.read_csv(TABLES_DIR / "Table4_Water_Response_Gaps.csv")
    w2 = df4[df4.contrast == "W2-W1"]
    w3 = df4[df4.contrast == "W3-W1"]

    assert len(w2) == 10
    assert len(w3) == 12

    assert abs(w2["observed_gap"].mean() - 4.974) < 1e-3
    assert abs(w2["simulated_gap"].mean() - 4.352) < 1e-3
    assert abs(w2["gap_bias"].mean() - (-0.622)) < 1e-3

    assert abs(w3["observed_gap"].mean() - 4.043) < 1e-3
    assert abs(w3["simulated_gap"].mean() - 6.210) < 1e-3
    assert abs(w3["gap_bias"].mean() - 2.167) < 1e-3

    w2_rmse = np.sqrt(np.mean((w2["simulated_gap"] - w2["observed_gap"])**2))
    w3_rmse = np.sqrt(np.mean((w3["simulated_gap"] - w3["observed_gap"])**2))
    assert abs(w2_rmse - 4.436) < 1e-3
    assert abs(w3_rmse - 4.924) < 1e-3

    w2_mae = np.mean(np.abs(w2["gap_bias"]))
    w3_mae = np.mean(np.abs(w3["gap_bias"]))
    assert abs(w2_mae - 3.458) < 1e-3
    assert abs(w3_mae - 4.430) < 1e-3


def test_table5_vegetative_and_harvest_dynamics():
    """Verify Table 5 vegetative growth and harvest event statistics against compiled report."""
    t5_path = TABLES_DIR / "Table5_Vegetative_Growth_Performance.csv"
    assert t5_path.exists(), f"Missing {t5_path}"
    df5 = pd.read_csv(t5_path).set_index(["season", "variable"])

    # Check key dynamic variables cited in manuscript
    # 25SP LAID
    assert abs(df5.loc[("25SP", "LAID")]["nrmse_pct"] - 15.6067) < 0.01
    assert abs(df5.loc[("25SP", "LAID")]["nse"] - 0.9431) < 0.01

    # 25SP FRESH_CUM
    assert abs(df5.loc[("25SP", "FRESH_CUM")]["nrmse_pct"] - 9.6569) < 0.01
    assert abs(df5.loc[("25SP", "FRESH_CUM")]["nse"] - 0.9678) < 0.01

    # 26SP FRESH_CUM
    assert abs(df5.loc[("26SP", "FRESH_CUM")]["nse"] - 0.8662) < 0.01

    # 25FA FRESH_CUM
    assert abs(df5.loc[("25FA", "FRESH_CUM")]["nse"] - 0.8686) < 0.01


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

