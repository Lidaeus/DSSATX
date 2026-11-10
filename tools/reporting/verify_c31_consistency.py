#!/usr/bin/env python3
"""
Automated Cross-Verification Script for Champion Candidate C31 Consistency.
Verifies that all cited numbers in the manuscript sections match underlying
tables, candidate manifest, and publication figures.
"""

import sys
import json
import re
import hashlib
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path("D:/Tomato_Cal")
CAND_DIR = PROJECT_ROOT / "workspace/candidates/candidate_c31_scheme1_dual_spring_precision"
TABLES_DIR = PROJECT_ROOT / "paper/02_Tables"
SECTIONS_DIR = PROJECT_ROOT / "paper/01_Sections"
FIGURES_DIR = PROJECT_ROOT / "paper/03_Figures"
PAPER_DATA_DIR = PROJECT_ROOT / "paper/paper_data"


def verify_candidate_manifest():
    print("1. Verifying Candidate C31 Manifest...")
    manifest_path = CAND_DIR / "candidate_manifest.json"
    assert manifest_path.exists(), f"Missing {manifest_path}"
    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["candidate_id"] == "C31", f"Wrong candidate_id: {data['candidate_id']}"
    assert data["realization_id"] == "c28_scheme1_tb1_92"

    kp = data["key_parameters"]
    assert kp["tb1"] == 9.2, f"Expected TB1=9.2, got {kp['tb1']}"
    assert abs(kp["kcan"] - 0.547134) < 1e-4
    assert abs(kp["sizlf"] - 290.261) < 1e-3
    assert abs(kp["dswbar"] - 5.64643) < 1e-4
    assert abs(kp["fl-sd"] - 22.3743) < 1e-4
    assert abs(kp["podur"] - 12.5693) < 1e-4
    assert abs(kp["lngsh"] - 18.0) < 1e-4
    assert abs(kp["slpf_25sp"] - 0.88) < 1e-4
    assert abs(kp["slpf_26sp"] - 0.89) < 1e-4
    assert abs(kp["sasc_ratio"] - 0.92) < 1e-4

    m = data["metrics"]
    # 26SP
    m26 = m["26sp_12trt"]
    assert abs(m26["r2"] - 0.701578) < 1e-3, f"26SP R2 mismatch: {m26['r2']}"
    assert abs(m26["nrmse_pct"] - 4.8947) < 1e-2, f"26SP NRMSE mismatch: {m26['nrmse_pct']}"
    assert abs(m26["nse"] - 0.701138) < 1e-3, f"26SP NSE mismatch: {m26['nse']}"
    assert abs(m26["d_index"] - 0.907166) < 1e-3, f"26SP d mismatch: {m26['d_index']}"

    # 25SP
    m25 = m["25sp_11trt"]
    assert abs(m25["r2"] - 0.880208) < 1e-3, f"25SP R2 mismatch: {m25['r2']}"
    assert abs(m25["nrmse_pct"] - 6.2393) < 1e-2, f"25SP NRMSE mismatch: {m25['nrmse_pct']}"

    # Two Springs
    m2s = m["twospring_23trt"]
    assert abs(m2s["r2"] - 0.724608) < 1e-3, f"Two springs R2 mismatch: {m2s['r2']}"
    assert abs(m2s["nrmse_pct"] - 5.5668) < 1e-2, f"Two springs NRMSE mismatch: {m2s['nrmse_pct']}"
    assert abs(m2s["nse"] - 0.572140) < 1e-3, f"Two springs NSE mismatch: {m2s['nse']}"

    # Grand 35
    m35 = m["grand_35trt"]
    assert abs(m35["r2"] - 0.984043) < 1e-3, f"Grand 35 R2 mismatch: {m35['r2']}"
    assert abs(m35["nrmse_pct"] - 7.6675) < 1e-2, f"Grand 35 NRMSE mismatch: {m35['nrmse_pct']}"
    assert abs(m35["nse"] - 0.974451) < 1e-3, f"Grand 35 NSE mismatch: {m35['nse']}"

    # 25FA
    mfa = m["25fa_12trt"]
    assert abs(mfa["nrmse_pct"] - 23.0731) < 1e-2, f"25FA NRMSE mismatch: {mfa['nrmse_pct']}"

    print("  [PASS] Candidate manifest parameters and metrics verified perfectly.")


def verify_tables():
    print("2. Verifying Underlying Tables in paper/02_Tables/...")
    # Table 1: Parameters
    t1_path = TABLES_DIR / "Table1_Genetic_Parameters_Comparison.csv"
    assert t1_path.exists(), f"Missing {t1_path}"
    df1 = pd.read_csv(t1_path)
    assert len(df1) == 168, f"Expected 168 parameter rows, got {len(df1)}"
    tb1_row = df1[df1["name"].str.lower() == "tb1"]
    assert len(tb1_row) == 1, "TB1 parameter missing from Table 1"
    tb1_val = float(tb1_row.iloc[0]["c31_value"])
    assert abs(tb1_val - 9.20) < 1e-4, f"Expected Table 1 TB1=9.20, got {tb1_val}"

    # Physiological N hierarchy in Table 1
    fnpgn1 = float(df1[df1["name"].str.lower() == "fnpgn1"].iloc[0]["c31_value"])
    fnpgn2 = float(df1[df1["name"].str.lower() == "fnpgn2"].iloc[0]["c31_value"])
    lnref = float(df1[df1["name"].str.lower() == "lnref"].iloc[0]["c31_value"])
    fnpgn3 = float(df1[df1["name"].str.lower() == "fnpgn3"].iloc[0]["c31_value"])
    fnpgn4 = float(df1[df1["name"].str.lower() == "fnpgn4"].iloc[0]["c31_value"])
    assert fnpgn1 < fnpgn2 <= lnref <= fnpgn3 <= fnpgn4, f"Physiological N hierarchy violated: {fnpgn1} < {fnpgn2} <= {lnref} <= {fnpgn3} <= {fnpgn4}"

    # Table 2: Model Statistical Performance
    t2_path = TABLES_DIR / "Table2_Model_Statistical_Performance_Yield.csv"
    assert t2_path.exists(), f"Missing {t2_path}"
    df2 = pd.read_csv(t2_path)
    groups = df2.set_index("group")

    # 26SP
    row26 = groups.loc["26SP"]
    assert abs(row26["r_squared"] - 0.7016) < 0.001
    assert abs(row26["nrmse_pct"] - 4.89) < 0.01
    assert abs(row26["nse"] - 0.7011) < 0.001
    assert abs(row26["d_index"] - 0.9072) < 0.001

    # 25SP
    row25 = groups.loc["25SP"]
    assert abs(row25["r_squared"] - 0.8802) < 0.001
    assert abs(row25["nrmse_pct"] - 6.24) < 0.01

    # two_springs
    row2s = groups.loc["two_springs"]
    assert abs(row2s["r_squared"] - 0.7246) < 0.001
    assert abs(row2s["nrmse_pct"] - 5.57) < 0.01
    assert abs(row2s["nse"] - 0.5721) < 0.001

    # all_35
    row35 = groups.loc["all_35"]
    assert abs(row35["r_squared"] - 0.9840) < 0.001
    assert abs(row35["nrmse_pct"] - 7.67) < 0.01
    assert abs(row35["nse"] - 0.9745) < 0.001

    # 25FA
    rowfa = groups.loc["25FA"]
    assert abs(rowfa["simulated_mean"] - 13.4093) < 0.01
    assert abs(rowfa["nrmse_pct"] - 23.07) < 0.01

    # Table 4: Water Response Gaps
    t4_path = TABLES_DIR / "Table4_Water_Response_Gaps.csv"
    assert t4_path.exists(), f"Missing {t4_path}"
    df4 = pd.read_csv(t4_path)

    # Filter spring seasons (25SP and 26SP)
    spring_gaps = df4[df4["season"].isin(["25SP", "26SP"])]
    assert len(spring_gaps) == 14, f"Expected 14 spring water gap rows, got {len(spring_gaps)}"

    for idx, row in spring_gaps.iterrows():
        sim_gap = row["simulated_gap"]
        contrast = row["contrast"]
        season = row["season"]
        nitrogen = row["nitrogen"]
        assert sim_gap > 0, f"Unphysical negative water response in spring: {season} {nitrogen} {contrast} = {sim_gap}"

    # Specific 26SP N0 check:
    sp26_n0_w2w1 = df4[(df4["season"] == "26SP") & (df4["nitrogen"] == "N0") & (df4["contrast"] == "W2-W1")].iloc[0]["simulated_gap"]
    sp26_n0_w3w1 = df4[(df4["season"] == "26SP") & (df4["nitrogen"] == "N0") & (df4["contrast"] == "W3-W1")].iloc[0]["simulated_gap"]
    assert abs(sp26_n0_w2w1 - 6.032) < 0.01, f"26SP N0 W2-W1 mismatch: {sp26_n0_w2w1}"
    assert abs(sp26_n0_w3w1 - 2.543) < 0.01, f"26SP N0 W3-W1 mismatch: {sp26_n0_w3w1}"

    # Specific 25SP N0 check:
    sp25_n0_w2w1 = df4[(df4["season"] == "25SP") & (df4["nitrogen"] == "N0") & (df4["contrast"] == "W2-W1")].iloc[0]["simulated_gap"]
    sp25_n0_w3w1 = df4[(df4["season"] == "25SP") & (df4["nitrogen"] == "N0") & (df4["contrast"] == "W3-W1")].iloc[0]["simulated_gap"]
    assert abs(sp25_n0_w2w1 - 12.446) < 0.01, f"25SP N0 W2-W1 mismatch: {sp25_n0_w2w1}"
    assert abs(sp25_n0_w3w1 - 13.259) < 0.01, f"25SP N0 W3-W1 mismatch: {sp25_n0_w3w1}"

    print("  [PASS] Tables 1, 2, and 4 verified with 100% positive water response ladders.")


def verify_manuscript_sections():
    print("3. Verifying Manuscript Sections in paper/01_Sections/...")
    target_files = [
        SECTIONS_DIR / "03_Results_Section.md",
        SECTIONS_DIR / "04_Discussion_Section.md",
        SECTIONS_DIR / "00_Combined_Results_Discussion.md",
    ]

    for fpath in target_files:
        assert fpath.exists(), f"Missing manuscript file: {fpath}"
        text = fpath.read_text(encoding="utf-8")

        # Zero active reference checks
        assert "8.4656" not in text, f"Stale TB1 8.4656 found in {fpath.name}"
        assert "Champion C23" not in text, f"Active reference to Champion C23 found in {fpath.name}"
        assert "Champion C16" not in text, f"Active reference to Champion C16 found in {fpath.name}"

        # Must mention Champion C31
        assert "C31" in text, f"Missing Champion C31 in {fpath.name}"

        # Verification of key metrics in results and combined sections
        if "Results" in fpath.name or "Combined" in fpath.name:
            assert "0.7016" in text or "0.702" in text, f"Missing 26SP R2 0.7016 in {fpath.name}"
            assert "4.89%" in text or "4.89" in text, f"Missing 26SP NRMSE 4.89% in {fpath.name}"
            assert "+0.7011" in text or "0.701" in text, f"Missing 26SP NSE +0.7011 in {fpath.name}"
            assert "0.8802" in text or "0.880" in text, f"Missing 25SP R2 0.8802 in {fpath.name}"
            assert "6.24%" in text or "6.24" in text, f"Missing 25SP NRMSE 6.24% in {fpath.name}"
            assert "0.7246" in text or "0.725" in text, f"Missing Two Springs R2 0.7246 in {fpath.name}"
            assert "5.57%" in text or "5.57" in text, f"Missing Two Springs NRMSE 5.57% in {fpath.name}"
            assert "7.67%" in text or "7.67" in text, f"Missing Grand 35 NRMSE 7.67% in {fpath.name}"
            assert "13.41" in text, f"Missing 25FA average yield 13.41 in {fpath.name}"
            assert "23.07%" in text or "23.07" in text, f"Missing 25FA NRMSE 23.07% in {fpath.name}"
            assert "9.20" in text or "9.2" in text, f"Missing TB1 9.20 in {fpath.name}"

    print("  [PASS] All manuscript sections verified for exact citations and zero stale references.")


def verify_figures_and_bundles():
    print("4. Verifying Figure Artifacts and Data Bundles...")
    fig_manifest = FIGURES_DIR / "figure_manifest.json"
    assert fig_manifest.exists(), f"Missing {fig_manifest}"
    with open(fig_manifest, "r", encoding="utf-8") as f:
        mdata = json.load(f)

    artifacts = mdata["artifacts"]
    assert len(artifacts) >= 200, f"Expected >= 200 artifacts, got {len(artifacts)}"

    # Check a sample of files and hashes
    for art in artifacts:
        art_path = FIGURES_DIR / art["path"]
        assert art_path.exists(), f"Missing artifact: {art_path}"
        sha = hashlib.sha256(art_path.read_bytes()).hexdigest()
        assert sha == art["sha256"], f"SHA mismatch on {art_path}: expected {art['sha256']}, got {sha}"

    # Verify data bundle manifests exist
    bundles = ["25SP", "26SP", "25FA", "terminal", "leaf_n", "ensemble", "conditional"]
    for b in bundles:
        b_manifest = PAPER_DATA_DIR / b / "paper_data_manifest.json"
        assert b_manifest.exists(), f"Missing data manifest for {b}"
        with open(b_manifest, "r", encoding="utf-8") as f:
            b_data = json.load(f)
        for rel_path, expected_sha in b_data.get("artifact_hashes", {}).items():
            fpath = PAPER_DATA_DIR / b / rel_path
            assert fpath.exists(), f"Missing file in {b}: {fpath}"
            fsha = hashlib.sha256(fpath.read_bytes()).hexdigest()
            assert fsha == expected_sha, f"SHA mismatch in bundle {b} for {rel_path}"

    print(f"  [PASS] figure_manifest.json ({len(artifacts)} artifacts) and all 7 data bundles verified.")


def main():
    print("================================================================================")
    print("Running Comprehensive C31 Cross-Verification Suite")
    print("================================================================================")
    verify_candidate_manifest()
    verify_tables()
    verify_manuscript_sections()
    verify_figures_and_bundles()
    print("================================================================================")
    print("ALL SCIENTIFIC CONSISTENCY CHECKS PASSED WITH 100% PRECISION!")
    print("================================================================================")


if __name__ == "__main__":
    main()
