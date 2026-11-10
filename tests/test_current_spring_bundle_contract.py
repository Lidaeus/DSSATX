"""Acceptance checks for the two retained, frozen spring bundles."""
import hashlib
import json
from pathlib import Path

import pytest

from src.common.input_manifest import verify_manifest_integrity
from src.common.experiment_inputs import parse_filex

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {'25SP': 'xxql2501_final_20261105', '26SP': 'xxql2601_final_20261105'}


def test_only_two_current_spring_bundles_remain():
    index = json.loads((ROOT / 'configs/experiments/current_bundles.json').read_text(encoding='utf-8'))
    assert {s: r['bundle_id'] for s, r in index['bundles'].items()} == EXPECTED
    assert {p.name for p in (ROOT / 'data/user/experiments').iterdir() if p.is_dir()} == set(EXPECTED.values())
    for season, name in EXPECTED.items():
        manifest = ROOT / 'data/user/experiments' / name / 'input_manifest.json'
        assert hashlib.sha256(manifest.read_bytes()).hexdigest() == index['bundles'][season]['manifest_sha256']


@pytest.mark.parametrize('season,code', [('25SP', 'XXQL2501'), ('26SP', 'XXQL2601')])
def test_retained_bundle_integrity_and_shared_prebasal_N(season, code):
    path = ROOT / 'data/user/experiments' / EXPECTED[season]
    verify_manifest_integrity(path)
    parsed = parse_filex(path / f'{code}.TMX')
    assert len(parsed['treatments']) == (8 if season == '25SP' else 12)
    for layers in parsed['initial_conditions'].values():
        assert (layers[0]['snh4'], layers[0]['sno3']) == pytest.approx((2.01, 8.41))
        for row in layers:
            if row['depth'] >= 80:
                assert (row['snh4'], row['sno3']) == pytest.approx((0.5, 1.0))
