"""Scientific acceptance checks for current soil input bundles."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pandas as pd
import pytest

from src.common.input_manifest import verify_manifest_integrity

ROOT = Path(__file__).resolve().parents[1]
BUNDLES = {
    "25SP": "xxql2501_corrected_20260923",
    "26SP": "xxql2601_corrected_20260923",
    "25FA": "xxql2502_corrected_20260923",
}


def test_project_contains_only_current_bundles() -> None:
    root = ROOT / "data/user/experiments"
    assert {p.name for p in root.iterdir() if p.is_dir()} == set(BUNDLES.values())
    registry = json.loads((ROOT / "configs/experiments/current_bundles.json").read_text(encoding="utf-8"))
    for season, bundle_id in BUNDLES.items():
        entry = registry["bundles"][season]
        assert entry["bundle_id"] == bundle_id
        manifest = root / bundle_id / "input_manifest.json"
        assert hashlib.sha256(manifest.read_bytes()).hexdigest() == entry["manifest_sha256"]


@pytest.mark.parametrize("season", list(BUNDLES))
def test_current_bundle_provenance_and_integrals(season: str) -> None:
    directory = ROOT / "data/user/experiments" / BUNDLES[season]
    manifest = verify_manifest_integrity(directory)
    assert manifest.bundle_id == BUNDLES[season]
    assert manifest.raw["source_workbooks_sha256"]
    audit = pd.read_csv(directory / "soil_inventory_reconciliation.csv")
    assert set(audit["column"]) >= {"no3_n", "nh4_n", "SH2O"}
    assert audit["relative_error_printed"].max() < 0.01
    assert (audit["measured_bottom_cm"] >= 60).all()


def test_measured_26sp_deep_n_overrides_default() -> None:
    directory = ROOT / "data/user/experiments" / BUNDLES["26SP"]
    audit = pd.read_csv(directory / "soil_depth_mapping_audit.csv")
    deep = audit[(audit["column"].isin(["no3_n", "nh4_n"])) &
                 (audit["target_bottom_cm"].isin([80, 100]))]
    assert len(deep) == 12 * 2 * 2
    assert deep["contributions"].map(lambda x: all(
        item["source"] == "measured" for item in json.loads(x))).all()


@pytest.mark.parametrize("season", ["25SP", "25FA"])
def test_unmeasured_deep_n_uses_requested_defaults(season: str) -> None:
    directory = ROOT / "data/user/experiments" / BUNDLES[season]
    audit = pd.read_csv(directory / "soil_depth_mapping_audit.csv")
    for col, value in [("no3_n", 1.0), ("nh4_n", 0.5)]:
        deep = audit[(audit["column"] == col) & (audit["target_bottom_cm"].isin([80, 100]))]
        assert len(deep) > 0
        assert (deep["mapped_value"] == value).all()
        assert deep["contributions"].map(lambda x: all(
            item["source"] == "dssat_default" for item in json.loads(x))).all()


def test_fall_yield_fraction_and_observations_agree() -> None:
    directory = ROOT / "data/user/experiments" / BUNDLES["25FA"]
    filet = pd.read_csv(directory / "FileT_values.csv")
    harvest = filet[filet["HFPOW"].notna()]
    assert (harvest["HPODW"] - harvest["HFPOW"] * 0.05).abs().max() < 1e-8
    uncertainty = pd.read_csv(directory / "observation_uncertainty.csv")
    assert (uncertainty["raw_sd"] > 0).all()


@pytest.mark.parametrize("season,source", [
    ("25SP", "2025春/2025春产量数据集.xlsx"),
    ("26SP", "2026春/2026春产量集.xlsx"),
    ("25FA", "2025秋/2025秋季产量集.xlsx"),
])
def test_harvest_fresh_yield_matches_current_workbook(season: str, source: str) -> None:
    workbook = ROOT / "data/user/ref/DSSAT文件" / source
    raw = pd.read_excel(workbook)
    if season == "25SP":
        raw["日期"] = pd.to_datetime(raw["日期"])
        raw = raw[(raw["小区号"].isin([2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14])) &
                  (raw["日期"] <= "2025-07-17")]
    expected = raw.groupby(["小区号", "日期"])["产量"].mean().groupby(level=0).apply(
        lambda s: sorted(s.tolist()))
    directory = ROOT / "data/user/experiments" / BUNDLES[season]
    actual = pd.read_csv(directory / "FileT_values.csv")
    actual = actual[actual["HFPOW"].notna()].groupby("TRNO")["HFPOW"].apply(
        lambda s: sorted(s.tolist()))
    assert set(actual.index) == set(expected.index)
    for trno in actual.index:
        assert actual[trno] == pytest.approx(expected[trno], rel=1e-9)
