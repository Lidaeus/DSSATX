"""Read-only numeric reconciliation of the October 27 bundle and Word evidence."""
from pathlib import Path
import hashlib
import json
import sys
from zipfile import ZipFile
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.common.input_manifest import verify_manifest_integrity

OUT = ROOT/'workspace/audits/bundle_word_methods_comparison_20261027'
WORD = Path('D:/三季节数据汇总/分析结果/69_更新原始数据重算干物质与NPK_20261027')
BUNDLE = ROOT/'data/user/experiments/xxql2601_refreshed_20261027'
DOC = Path('D:/三季节数据汇总/番茄与茄子_2026干物质与NPK重算_蓝字版_20261027.docx')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    snapshots = []
    for name in ['2026春茎叶果氮磷钾.xlsx','2026春品质指标集-修正.xlsx',
                 '2026春生长指标集结果.xlsx','2026春产量集.xlsx']:
        a=ROOT/'workspace/audits/spring_input_refresh_20261027/source_snapshot/2026春'/name
        b=WORD/'输入快照'/name
        snapshots.append(dict(file=name,bundle_sha256=sha(a),word_sha256=sha(b),same=sha(a)==sha(b)))
    assert all(r['same'] for r in snapshots)
    for code in ['xxql2501','xxql2601']:
        verify_manifest_integrity(ROOT/'data/user/experiments'/f'{code}_refreshed_20261027')
    meta=pd.read_csv(BUNDLE/'treatment_metadata.csv').rename(columns={
        'treatment':'trno','water_level':'W','nitrogen_level':'N'})[['trno','W','N']]
    def mapped(frame):
        return frame.merge(meta,on='trno',validate='many_to_one').rename(columns={'rep':'block'})
    checks=[]
    details=[]
    def compare(label,a,b,keys,acol,bcol):
        aa=a[keys+[acol]].rename(columns={acol:'bundle_value'})
        bb=b[keys+[bcol]].rename(columns={bcol:'word_value'})
        joined=aa.merge(bb,on=keys,how='outer',indicator=True,validate='one_to_one')
        assert joined['_merge'].eq('both').all(),label
        joined['difference']=joined.bundle_value-joined.word_value
        maximum=float(joined.difference.abs().max())
        assert np.allclose(joined.bundle_value,joined.word_value,atol=1e-8,rtol=1e-12),label
        checks.append(dict(comparison=label,paired_values=len(joined),max_absolute_difference=maximum))
        joined['comparison']=label
        details.append(joined.drop(columns='_merge'))

    keys=['date','W','N','block']
    growth=mapped(pd.read_csv(BUNDLE/'growth_replicates.csv'))
    harvest=mapped(pd.read_csv(BUNDLE/'harvest_replicates.csv'))
    wg=pd.read_csv(WORD/'数据/当前茎叶干物质_逐小区.csv')
    for organ,col in [('stem','SWAD'),('leaf','LWAD')]:
        compare(f'observed_{organ}_dry_mass',growth,wg[wg.organ==organ],keys,col,'dry_kg_ha')
    wh=pd.read_csv(WORD/'数据/五次采收鲜干转换与NPK携出_逐小区.csv')
    wn=wh[wh.element=='N']
    for col,wordcol in [('HFPOW','fresh_yield_kg_ha'),('PDMCD','dry_fraction'),
                        ('HPODW','fruit_drymatter_kg_ha'),('CHPDT','cumulative_drymatter_kg_ha')]:
        compare(col,harvest,wn,keys,col,wordcol)
    for element in ['N','P','K']:
        compare(f'harvest_{element}_export',harvest,wh[wh.element==element],keys,
                f'harvest_{element}_kg_ha','export_kg_ha')
    audit=mapped(pd.read_csv(BUNDLE/'standing_npk_calculation_audit.csv')).rename(columns={
        'growth_date':'date','nutrient':'element'})
    audit['organ']=audit.organ.map({'茎':'stem','叶':'leaf'})
    ws=pd.read_csv(WORD/'数据/全部五节点器官及累计NPK_逐小区.csv')
    observed=ws[ws.organ.isin(['stem','leaf']) & ws.origin.eq('CURRENT_OBSERVED_DRYWEIGHT')]
    compare('observed_stem_leaf_NPK_stock',audit,observed,keys+['organ','element'],'amount_kg_ha','value')
    # Compare full-precision means/SD, rather than fixed-width model-interface values.
    uncertainty=mapped(pd.read_csv(BUNDLE/'observation_uncertainty.csv'))
    stats=pd.read_csv(WORD/'统计/Duncan处理均值SD字母.csv')
    for variable,metric in [('SNAM','N_stem'),('LNAM','N_leaf')]:
        a=uncertainty[uncertainty.variable==variable]
        b=stats[(stats.metric==metric)&stats.date.isin(growth.date.unique())]
        compare(f'{variable}_source_mean',a,b,['date','W','N'],'unrounded_source_mean','mean')
        compare(f'{variable}_sample_SD',a,b,['date','W','N'],'raw_sd','SD')

    end='2026-07-17'
    bdm=growth[growth.date==end][['W','N','block','SWAD','LWAD']].rename(columns={'SWAD':'stem','LWAD':'leaf'})
    dry=harvest.groupby(['W','N','block'],as_index=False).HPODW.sum().rename(columns={'HPODW':'fruit'})
    bdm=bdm.merge(dry,on=['W','N','block'],validate='one_to_one')
    bdm['vegetative']=bdm.stem+bdm.leaf
    bdm['total']=bdm.vegetative+bdm.fruit
    wdm=pd.read_csv(WORD/'数据/拉秧期地上部干物质构成_逐小区.csv')
    for col in ['stem','leaf','fruit','vegetative','total']:
        compare(f'terminal_{col}_mass_reconstructed',bdm,wdm,['W','N','block'],col,col)
    ledger=pd.read_csv(WORD/'数据/五节点在株与采出NPK分项账本.csv')
    totals=[]
    for element in ['N','P','K']:
        standing=audit[(audit.date==end)&(audit.element==element)].groupby(['W','N','block']).amount_kg_ha.sum()
        exported=harvest.groupby(['W','N','block'])[f'harvest_{element}_kg_ha'].sum()
        z=(standing+exported).rename('total').reset_index();z['element']=element;totals.append(z)
    totals=pd.concat(totals,ignore_index=True)
    compare('terminal_aboveground_NPK_reconstructed',totals,ledger[ledger.date==end],
            ['W','N','block','element'],'total','aboveground_total_kg_ha')
    for col in ['mean','std']:
        z=bdm.groupby(['W','N']).total.agg(col).rename('value').reset_index()
        b=stats[(stats.family=='biomass')&(stats.metric=='total')&(stats.date==end)]
        compare(f'terminal_total_DM_{col}',z,b,['W','N'],'value','mean' if col=='mean' else 'SD')

    # Interface precision and different aggregation levels must remain visible.
    filea=pd.read_csv(BUNDLE/'FileA_values.csv').merge(meta,left_on='TRNO',right_on='trno')
    dm_means=bdm.groupby(['W','N'])[['stem','leaf','fruit','total']].mean().reset_index()
    rounded=filea.merge(dm_means,on=['W','N'],validate='one_to_one')
    precision=[]
    for a,b in [('SWAM','stem'),('LWAM','leaf'),('HWAH','fruit')]:
        precision.append(dict(bundle_field=a,max_absolute_rounding_difference=float((rounded[a]-rounded[b]).abs().max())))
    irrigation=pd.read_csv(BUNDLE/'irrigation_event_audit.csv')
    water_totals=irrigation.groupby('trno').mm.sum()
    first_irrigation=irrigation[irrigation.date=='2026-03-14'].mm.unique().tolist()
    new_growth=growth.groupby('date').agg(height_cm=('株高','mean'),LAI=('LAI','mean'))
    new_growth.to_csv(OUT/'current_growth_means.csv')
    reference_heights=[42.50,105.75,144.65,167.52]
    growth_discrepancies=[]
    for (day,r),oldheight in zip(new_growth.iterrows(),reference_heights):
        growth_discrepancies.append(dict(date=day,bundle_current_height_cm=float(r.height_cm),
            word_paragraph_P0181_height_cm=oldheight,difference_cm=float(r.height_cm-oldheight),LAI_current=float(r.LAI)))
    # Shared-source model estimates exist only in the Word accounting project.
    model_parts=ws[ws.organ.isin(['stem','leaf']) & ws.origin.eq('FROZEN_DSSAT_MISSING_NODE')]
    sample=wdm[(wdm.W=='W1')&(wdm.N=='N0')]
    sd_example=dict(W='W1',N='N0',direct_total_sample_SD=float(sample.total.std(ddof=1)),
        invalid_independent_component_RSS=float(np.sqrt(sum(sample[c].std(ddof=1)**2 for c in ['stem','leaf','fruit']))))
    # Verify that the cited analysis really supplies the named Word tables.
    ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    with ZipFile(DOC) as archive:
        document=ET.fromstring(archive.read('word/document.xml'))
    tables=document.findall('w:body/w:tbl',ns)
    document_checks=[]
    import re
    for element,table_no in [('N',5),('P',6),('K',7)]:
        current_water=''
        for row in tables[table_no-1].findall('w:tr',ns)[2:]:
            cells=[''.join(t.text or '' for t in c.findall('.//w:t',ns))
                   for c in row.findall('w:tc',ns)]
            if cells[0].strip():current_water=cells[0].strip()
            nitrogen=cells[1].strip()
            if current_water not in ['W1','W2','W3'] or nitrogen not in ['N0','N1','N2','N3']:continue
            assert len(cells)==14
            for node,day in enumerate(['2026-05-02','2026-05-26',end]):
                for organ_no,organ in enumerate(['stem','leaf','fruit','accounted_total']):
                    text=cells[2+node*4+organ_no]
                    match=re.match(r'([-+]?\d+(?:\.\d+)?)(.*)',text)
                    assert match,text
                    expected=stats[(stats.metric==f'{element}_{organ}')&(stats.date==day)&
                        (stats.W==current_water)&(stats.N==nitrogen)].iloc[0]
                    assert float(match[1])==float(f'{expected["mean"]:.2f}'),text
                    assert match[2]==expected['letters'],text
                    document_checks.append(dict(table=table_no,W=current_water,N=nitrogen,date=day,
                        metric=f'{element}_{organ}',printed=text,expected_mean=expected['mean'],letters=expected['letters']))
    assert len(document_checks)==432
    pd.DataFrame(document_checks).to_csv(OUT/'word_table_5_to_7_value_and_letter_checks.csv',index=False)
    result=dict(document=str(DOC),document_sha256=sha(DOC),word_analysis_directory=str(WORD),
        bundle=str(BUNDLE),snapshots=snapshots,checks=checks,
        common_full_precision_compared_values=sum(c['paired_values'] for c in checks),
        largest_absolute_difference=max(c['max_absolute_difference'] for c in checks),
        interface_rounding=precision,growth_paragraph_version_discrepancies=growth_discrepancies,
        first_irrigation_in_bundle_mm=first_irrigation,
        whole_season_irrigation_mm_range=[float(water_totals.min()),float(water_totals.max())],
        word_model_only_stem_leaf_NPK_rows=len(model_parts),
        word_model_only_stem_leaf_dates=sorted(model_parts.date.unique()),
        covariance_example=sd_example,
        word_table_5_to_7_value_and_letter_checks=len(document_checks),
        note='Reconstructed totals are audit-only; no frozen bundle fields have been added or changed.')
    pd.DataFrame(checks).to_csv(OUT/'numeric_reconciliation_summary.csv',index=False)
    pd.concat(details,ignore_index=True).to_csv(OUT/'numeric_reconciliation_details.csv',index=False)
    (OUT/'comparison_evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
