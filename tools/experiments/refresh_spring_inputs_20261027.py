"""Refresh the two spring input bundles from explicitly selected October workbooks.

The October 10 transformation contract is retained. Old bundles and historical
model runs remain frozen. The source workbooks are copied byte for byte into an
audit snapshot; spreadsheet formulas and formatting are never rewritten.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import shutil
import sys

import numpy as np
import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils.cell import coordinate_from_string, column_index_from_string, get_column_letter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.experiments import rebuild_current_bundles as legacy
from src.common.input_manifest import verify_manifest_integrity
from src.calibration.audit_observations import audit_observation_bundle, read_dssat_observation_table
from src.calibration.build_pest import _read_tmt_harvest_events, _read_tmt_process_points

STAMP = '20261027'
DATE = '2026-10-27'
AUDIT = ROOT / 'workspace/audits' / f'spring_input_refresh_{STAMP}'
STAGING = ROOT / 'workspace/staging' / f'spring_input_refresh_{STAMP}'
REFERENCE = legacy.REF
SEASONS = ('25SP', '26SP')


def snapshot_sources(source_root: Path) -> tuple[Path, list[dict]]:
    snapshot = AUDIT / 'source_snapshot'
    snapshot.mkdir(parents=True)
    records = []
    for season in SEASONS:
        folder = legacy.SPECS[season]['folder']
        (snapshot / folder).mkdir()
        for source in sorted((source_root / folder).glob('*.xlsx')):
            target = snapshot / folder / source.name
            shutil.copy2(source, target)
            if legacy.sha(source) != legacy.sha(target):
                raise ValueError(f'Snapshot copy mismatch: {source}')
            formula_book = load_workbook(target, data_only=False)
            cached_book = load_workbook(target, data_only=True)
            errors, uncached = [], []
            for sheet in formula_book:
                for cells in sheet:
                    for cell in cells:
                        cached = cached_book[sheet.title][cell.coordinate]
                        if cached.data_type == 'e':
                            errors.append(f'{sheet.title}!{cell.coordinate}: {cached.value}')
                        if cell.data_type == 'f' and cached.value is None:
                            uncached.append(f'{sheet.title}!{cell.coordinate}')
            formula_book.close()
            cached_book.close()
            if errors or uncached:
                raise ValueError(f'Unusable Excel values in {source}: {errors}; uncached={uncached}')
            previous_name = source.name.replace('-修正', '') if season == '26SP' else source.name
            previous = REFERENCE / folder / previous_name
            records.append(dict(season=season, origin=str(source), snapshot=str(target),
                sha256=legacy.sha(source), size_bytes=source.stat().st_size,
                differs_from_maintained_source=(not previous.exists() or legacy.sha(previous) != legacy.sha(source)),
                excel_error_count=0, uncached_formula_count=0))
    shared = REFERENCE / '三季实验初始硝态氮铵态氮参考.xlsx'
    shutil.copy2(shared, snapshot / shared.name)
    records.append(dict(season='shared', origin=str(shared), snapshot=str(snapshot/shared.name),
                        sha256=legacy.sha(shared), role='inherited_approved_prebasal_N'))
    return snapshot, records


def remap_manual_markers(snapshot: Path) -> pd.DataFrame:
    """Do not reuse a cell address after source rows have been removed/reordered."""
    markers = pd.read_csv(REFERENCE / '人工处理值标记.csv')
    output, audit = [], []
    for _, marker in markers.iterrows():
        relative = str(marker['文件']).replace('\\', '/')
        before = pd.read_excel(REFERENCE / relative, sheet_name=marker['工作表'])
        after = pd.read_excel(snapshot / relative, sheet_name=marker['工作表'])
        letter, number = coordinate_from_string(marker['位置'])
        field = before.columns[column_index_from_string(letter)-1]
        row = before.iloc[number-2]
        keys = ['小区号', '重复'] + (['日期'] if '品质' in relative else ['取样日期', '土层深度'])
        match = pd.Series(True, index=after.index)
        for key in keys:
            match &= after[key].eq(row[key])
        hits = after.loc[match]
        if len(hits) != 1 or not np.isclose(float(hits.iloc[0][field]), float(row[field]), atol=1e-12, rtol=0):
            raise ValueError(f'Manual-marker identity/value cannot be carried forward: {relative} {marker["位置"]}')
        position = get_column_letter(after.columns.get_loc(field)+1) + str(int(hits.index[0])+2)
        updated = marker.to_dict()
        updated['位置'] = position
        output.append(updated)
        audit.append(dict(file=relative, sheet=marker['工作表'], old_cell=marker['位置'], new_cell=position,
            field=field, source_key=';'.join(f'{key}={row[key]}' for key in keys), value=float(row[field]),
            status='same_record_same_value'))
    result = pd.DataFrame(output)
    result.to_csv(snapshot / '人工处理值标记.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(audit).to_csv(AUDIT / 'manual_marker_relocation.csv', index=False, encoding='utf-8-sig')
    return result


def compare_observations(old: Path, new: Path, excode: str) -> list[dict]:
    changes = []
    for suffix, keys in [('TMA', ['TRNO']), ('TMT', ['TRNO', 'DATE'])]:
        a = read_dssat_observation_table(old/f'{excode}.{suffix}').set_index(keys)
        b = read_dssat_observation_table(new/f'{excode}.{suffix}').set_index(keys)
        if set(a.index) != set(b.index):
            raise ValueError(f'Unexpected treatment/date change in {suffix}')
        for key in a.index:
            for field in b.columns:
                x, y = float(a.loc[key, field]), float(b.loc[key, field])
                if not np.isclose(x, y, atol=1e-10, rtol=0, equal_nan=True):
                    changes.append(dict(file=f'{excode}.{suffix}', key=str(key), variable=field, old=x, new=y))
    return changes


def independent_filea_check(season: str, output: Path) -> dict:
    """Recompute FileA from source records, independently of generated CSVs."""
    spec = legacy.SPECS[season]
    g = legacy.canonical(season, spec['growth'])
    y = legacy.canonical(season, spec['yield_'])
    quality_name, quality_sheet, water = spec['quality']
    q = legacy.canonical(season, (quality_name, quality_sheet, '小区号', '重复', '日期'))
    a = read_dssat_observation_table(output/f'{spec["excode"]}.TMA').set_index('TRNO')
    checked = 0
    for tn in spec['treatments']:
        gg = g[g.trno == tn]
        valid = gg[gg['茎干重'].notna() & gg['叶干重'].notna()]
        last = valid[valid.date == valid.date.max()]
        dry_total = []
        for rep, yy in y[y.trno == tn].groupby('rep'):
            qq = q[(q.trno == tn) & (q.rep == rep)].sort_values('date')
            moisture = np.interp(yy.date.map(pd.Timestamp.toordinal), qq.date.map(pd.Timestamp.toordinal), qq[water])
            dry_total.append(float(np.sum(yy['产量'].to_numpy() * (1-moisture))))
        expected = dict(LWAM=round(last['叶干重'].mean()*27), SWAM=round(last['茎干重'].mean()*27),
            LAIX=round(gg.groupby('date')['LAI'].mean().max(), 3),
            HWAH=round(np.mean(dry_total)), HWAHF=round(y[y.trno==tn].groupby('rep')['产量'].sum().mean()))
        for field, value in expected.items():
            if not np.isclose(float(a.loc[tn, field]), value, atol=.000001, rtol=0):
                raise ValueError(f'Independent FileA check failed: {season} TN{tn} {field}')
            checked += 1
    return dict(checked_cells=checked, failures=0,
                method='direct_source_terminal_mass_peak_LAI_and_per_plot_quality_weighted_dry_yield')


def build(source_root: Path, promote: bool) -> None:
    index_path = ROOT / 'configs/experiments/current_bundles.json'
    original_index_bytes = index_path.read_bytes()
    index = json.loads(original_index_bytes)
    if AUDIT.exists() or STAGING.exists():
        raise FileExistsError('Refuse to overwrite an existing October 27 audit/staging directory')
    baselines = {}
    for season in SEASONS:
        old = ROOT/'data/user/experiments'/index['bundles'][season]['bundle_id']
        verify_manifest_integrity(old)
        if legacy.sha(old/'input_manifest.json') != index['bundles'][season]['manifest_sha256']:
            raise ValueError(f'Current index/manifest mismatch for {season}')
        baselines[season] = old
    AUDIT.mkdir(parents=True)
    (AUDIT/'current_bundles.before.json').write_bytes(original_index_bytes)
    snapshot, sources = snapshot_sources(source_root)
    markers = remap_manual_markers(snapshot)
    legacy.REF = snapshot
    legacy.DATE = DATE
    legacy.SPECS = copy.deepcopy(legacy.SPECS)
    legacy.SPECS['26SP']['quality'] = ('2026春品质指标集-修正.xlsx', 'Sheet1', '半果含水率')
    results, all_changes = {}, []
    for season in SEASONS:
        spec = legacy.SPECS[season]
        excode = spec['excode']
        old = baselines[season]
        out = STAGING/f'{excode.lower()}_refreshed_{STAMP}'
        out.mkdir(parents=True)
        for name in ['XXTW2403.WTH', 'TMGRO048.CUL', 'TMGRO048.ECO', 'TMGRO048.SPE']:
            shutil.copy2(old/name, out/name)
        growth, harvest = legacy.observation_outputs(season, out, old)
        water = legacy.soil_water(season, out)
        chem = legacy.soil_chemistry(season)
        legacy.filex_outputs(season, out, old, chem, water, harvest, growth)
        markers[markers['文件'].str.startswith(spec['folder'])].to_csv(out/'manual_value_markers.csv', index=False)
        decisions = json.loads((old/'decision_record.json').read_text(encoding='utf-8'))
        decisions.update(date=DATE, refresh_scope='25SP_and_26SP_latest_source_workbooks',
            source_folder=str(source_root/spec['folder']),
            quality_workbook=spec['quality'][0],
            manual_marker_identity='relocated_by_treatment_replicate_date_and_field;values_verified',
            NPK_growth_alignment='exact_current_source_dates;legacy_June03_to_June02_proxy_not_used',
            historical_run_policy='existing_bundles_and_calibration_results_remain_frozen')
        legacy.write_json(out/'decision_record.json', decisions)
        changes = compare_observations(old, out, excode)
        all_changes.extend(changes)
        pd.DataFrame(changes).to_csv(out/'observation_value_changes.csv', index=False)
        direct = independent_filea_check(season, out)
        audit, reconciliation = audit_observation_bundle(out)
        legacy.write_json(out/'input_quality_audit.json', audit)
        reconciliation.to_csv(out/'harvest_increment_reconciliation.csv', index=False)
        if audit['error_count']:
            raise ValueError(audit['findings'])
        smoke = legacy.smoke(out, genotype_dir=out)
        legacy.write_json(out/'dssat_smoke_report.json', smoke)
        # Exercise the existing formal-calibration readers, not only a CSV parser.
        process = _read_tmt_process_points(str(out/f'{excode}.TMT'))
        events = _read_tmt_harvest_events(str(out/f'{excode}.TMT'))
        if set(process) != set(spec['treatments']) or set(events) != set(spec['treatments']):
            raise ValueError('Formal calibration reader lost treatments')
        acceptance = dict(independent_FileA=direct, input_audit_errors=0,
            process_treatments_read=len(process), harvest_treatments_read=len(events),
            harvest_events_in_source=int(harvest.groupby(['trno','date']).ngroups),
            NPK_source_rows=len(pd.read_csv(out/'plant_npk_source_values.csv')),
            exact_NPK_dates=sorted(pd.read_csv(out/'plant_npk_source_values.csv').date.unique()),
            smoke_treatments=smoke['expected_treatments'], smoke_passed=True)
        legacy.write_json(out/'calibration_reader_acceptance.json', acceptance)
        provenance = dict(generator=str(Path(__file__).relative_to(ROOT)), generator_sha256=legacy.sha(__file__),
            transformation_helper_sha256=legacy.sha(legacy.__file__), baseline_bundle=old.name,
            baseline_manifest_sha256=legacy.sha(old/'input_manifest.json'),
            sources=[r for r in sources if r['season'] in [season, 'shared']],
            marker_registry_source=str(REFERENCE/'人工处理值标记.csv'),
            marker_registry_sha256=legacy.sha(REFERENCE/'人工处理值标记.csv'))
        legacy.write_json(out/'source_provenance.json', provenance)
        preserved={name:legacy.sha(out/name)==legacy.sha(old/name) for name in
                   ['XXTW2403.WTH','TMGRO048.CUL','TMGRO048.ECO','TMGRO048.SPE','SOIL.SOL']}
        if not all(preserved.values()):
            raise ValueError(f'Unintended weather/genotype/soil-profile change: {preserved}')
        manifest=dict(bundle_id=out.name,created=DATE,season=season,immutable=True,
            intended_use='calibration_and_validation_inputs;not_calibrated_results',
            source_provenance_sha256=legacy.sha(out/'source_provenance.json'),generator_sha256=legacy.sha(__file__),
            decision_record=decisions,engineering_checks='input_audit_independent_FileA_and_exact_bundle_DSSAT_smoke_passed',
            files=[dict(name=p.name,sha256=legacy.sha(p),size_bytes=p.stat().st_size) for p in sorted(out.iterdir()) if p.is_file()])
        legacy.write_json(out/'input_manifest.json',manifest)
        verify_manifest_integrity(out)
        results[season]=dict(bundle_id=out.name,baseline_bundle=old.name,
            TMA_changed_cells=sum(r['file'].endswith('.TMA') for r in changes),
            TMT_changed_cells=sum(r['file'].endswith('.TMT') for r in changes),
            TMX_identical_to_previous=legacy.sha(out/f'{excode}.TMX')==legacy.sha(old/f'{excode}.TMX'),
            preserved=preserved,acceptance=acceptance,
            manifest_sha256=legacy.sha(out/'input_manifest.json'))
        print(json.dumps({season:results[season]},ensure_ascii=False),flush=True)
    # The selected source bytes and old index must remain stable during generation.
    for r in sources:
        if legacy.sha(r['origin']) != r['sha256']:
            raise ValueError(f'Source changed while building: {r["origin"]}')
    if index_path.read_bytes() != original_index_bytes:
        raise ValueError('Current index changed concurrently; refusing promotion')
    pd.DataFrame(all_changes).to_csv(AUDIT/'observation_value_changes.csv',index=False)
    legacy.write_json(AUDIT/'source_inventory.json',sources)
    if promote:
        for season, r in results.items():
            destination=ROOT/'data/user/experiments'/r['bundle_id']
            if destination.exists():raise FileExistsError(destination)
        for season,r in results.items():
            destination=ROOT/'data/user/experiments'/r['bundle_id']
            shutil.copytree(STAGING/r['bundle_id'],destination)
            verify_manifest_integrity(destination)
            index['bundles'][season]={'bundle_id':r['bundle_id'],'manifest_sha256':r['manifest_sha256']}
        index.update(as_of=DATE,notes='Two spring workbooks refreshed 2026-10-27; exact-bundle DSSAT smoke and source-value checks passed; autumn unchanged')
        replacement=index_path.with_suffix('.json.tmp')
        legacy.write_json(replacement,index)
        replacement.replace(index_path)
    legacy.write_json(AUDIT/'refresh_summary.json',dict(date=DATE,promoted=promote,results=results,
        source_root=str(source_root),blocking_decisions=[],marker_records_relocated=len(markers)))


if __name__ == '__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=Path('D:/三季节数据汇总'))
    parser.add_argument('--promote',action='store_true')
    args=parser.parse_args()
    build(args.source_root,args.promote)
