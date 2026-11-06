"""Read-only yield influence and soil-input reconciliation for the selected all12 run."""
from pathlib import Path
import datetime as dt
import hashlib
import json
import sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.common.experiment_inputs import parse_filex
from src.common.input_manifest import verify_manifest_integrity
from tools.experiments.rebuild_current_bundles import soil_chemistry

RUN=ROOT/'workspace/runs/eggplant_26sp_all12_robust_joint65_200x5_20261012'
OUT=RUN/'soil_yield_audit_20261013'
REF=ROOT/'data/user/ref/DSSAT文件'

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')

def fit(q):
    o=q.observed.to_numpy(float);s=q.simulated.to_numpy(float);e=s-o
    return dict(n=len(o),R2=float(np.corrcoef(o,s)[0,1]**2),
       d=float(1-(e**2).sum()/((abs(s-o.mean())+abs(o-o.mean()))**2).sum()),
       RMSE=float(np.sqrt((e**2).mean())),MBE=float(e.mean()))

def sections(path):
    lines=path.read_text(encoding='utf-8').splitlines();rows=[];section=False;layer=False
    for line in lines:
        if line.startswith('*'):section=line.upper().startswith('*SOIL ANALYSIS');layer=False
        if not section:continue
        if line.startswith('@A'):layer='SABL' in line;continue
        if not layer or not line.strip():continue
        x=line.split()
        if len(x)==10:rows.append(dict(factor=int(x[0]),bottom=float(x[1]),bd=float(x[2]),soc=float(x[3]),tn_pct=float(x[4]),ph=float(x[5]),ap=float(x[7]),ak=float(x[8])))
    return pd.DataFrame(rows)

def native(path):
    """Parse treatment numbers from DSSAT headers, never infer from run order."""
    rows=[];tn=None;cols=None
    for line in path.read_text(errors='replace').splitlines():
        if line.startswith(' TREATMENT'):tn=int(line.split()[1])
        elif line.startswith('@YEAR'):cols=line[1:].split()
        elif cols and tn is not None and line.strip() and line.strip()[0].isdigit():
            values=line.split()
            if len(values)==len(cols):rows.append(dict(zip(cols,map(float,values)))|dict(trno=tn))
    return pd.DataFrame(rows)

def main():
    OUT.mkdir(exist_ok=True)
    pair_path=RUN/'result_review_20261013/terminal_yield_pairs.csv';pairs=pd.read_csv(pair_path)
    pairs=pairs[pairs.season_id.isin(['25SP','25FA'])]
    metric_rows=[];influence=[]
    for season in ['25SP','25FA']:
        scopes=['validation_W1_W3']+(['all12_including_W2_diagnostic'] if season=='25FA' else [])
        for scope in scopes:
            for var in ['CHPDT','CHFPW']:
                q=pairs[(pairs.season_id==season)&(pairs.variable==var)]
                if scope=='validation_W1_W3':q=q[q.dataset_role=='validation']
                base=fit(q);metric_rows.append(dict(season_id=season,scope=scope,variable=var,**base))
                for row in q.itertuples():
                    without=fit(q[q.trno!=row.trno])
                    influence.append(dict(season_id=season,scope=scope,variable=var,trno=int(row.trno),water_level=row.water_level,
                      nitrogen_level=row.nitrogen_level,role=row.dataset_role,observed=row.observed,simulated=row.simulated,
                      baseline_R2=base['R2'],R2_without=without['R2'],delta_R2=without['R2']-base['R2'],
                      baseline_d=base['d'],d_without=without['d'],delta_d=without['d']-base['d']))
    pd.DataFrame(metric_rows).to_csv(OUT/'terminal_metrics.csv',index=False)
    pd.DataFrame(influence).to_csv(OUT/'leave_one_treatment_out.csv',index=False)
    summary=[];layerrows=[];source_checks=[];inputs=[]
    for season,code,bundle_name in [('25SP','XXQL2501','xxql2501_refreshed_20261010'),('25FA','XXQL2502','xxql2502_refreshed_20261010')]:
        bundle=ROOT/'data/user/experiments'/bundle_name;work=RUN/'evaluation'/season
        verify_manifest_integrity(bundle)
        provenance=json.loads((bundle/'source_provenance.json').read_text(encoding='utf-8'))
        for source in provenance['sources']:
            file=ROOT/source['path']
            if '养分' in file.name or '有机质' in file.name or '参考.xlsx' in file.name:
                source_checks.append(dict(path=str(file),expected=source['sha256'],actual=sha(file),unchanged=sha(file)==source['sha256']))
        input_file=work/(code+'.TMX');source_file=bundle/(code+'.TMX')
        assert [x for x in input_file.read_text().splitlines() if x.strip()]==[x for x in source_file.read_text().splitlines() if x.strip()]
        inputs.append(dict(season_id=season,TMX_sha256=sha(input_file),bundle_TMX_sha256=sha(source_file),quantitative_lines_unchanged=True,
          preparation_format_change='one blank separator removed by approved initial-condition normalizer'))
        parsed=parse_filex(input_file);sa=sections(input_file)
        mapping=pd.read_csv(bundle/'soil_depth_mapping_audit.csv')
        meta=pd.read_csv(bundle/'treatment_metadata.csv').set_index('treatment')
        source=soil_chemistry(season);source.to_csv(OUT/(season+'_source_chemistry.csv'),index=False)
        ni=native(work/'SoilNi.OUT')
        fertilizer=pd.read_csv(bundle/'fertilizer_event_audit.csv')
        for tn,factors in parsed['treatments'].items():
            assert factors['SA']==tn and factors['IC']==tn
            layer=sa[sa.factor==factors['SA']].sort_values('bottom').copy()
            initial=parsed['initial_conditions'][factors['IC']]
            assert len(layer)==len(initial)==10
            soil_mass=[];previous=0
            for l,ic in zip(layer.itertuples(),initial):
                assert l.bottom==ic['depth']
                m=(l.bottom-previous)*l.bd*.1;soil_mass.append(m);previous=l.bottom
                expected={k:float(mapping[(mapping.trno==tn)&(mapping.column==col)&(mapping.target_bottom_cm==l.bottom)].mapped_value.iloc[0])
                  for k,col in [('soc','organic_c_pct'),('tn_pct','total_n_gkg'),('ph','ph'),('ap','available_p'),('ak','available_k')]}
                expected['tn_pct']/=10
                tolerance=dict(soc=.00501,tn_pct=.000501,ph=.00501,ap=.05001,ak=.05001)
                for k,v in expected.items():assert abs(getattr(l,k)-v)<=tolerance[k],(season,tn,l.bottom,k,v)
                layerrows.append(dict(season_id=season,trno=tn,depth_bottom_cm=l.bottom,soc_pct=l.soc,total_N_pct=l.tn_pct,
                  available_P_mgkg=l.ap,available_K_cmolkg=l.ak,NO3_mgNkg=ic['sno3'],NH4_mgNkg=ic['snh4'],mapping_readback_passed=True))
            initial_total=sum((ic['sno3']+ic['snh4'])*m for ic,m in zip(initial,soil_mass))
            initial_100=sum((ic['sno3']+ic['snh4'])*m for ic,m in zip(initial,soil_mass) if ic['depth']<=100)
            n=ni[ni.trno==tn].sort_values(['YEAR','DOY']);first=n.iloc[0];last=n.iloc[-1]
            total_N_fert=float(fertilizer[fertilizer['施肥方案F']==factors['MF']]['N kg/ha'].sum())
            assert abs(first.NIAD-initial_total)<=.11 and abs(last.NAPC-total_N_fert)<=.51
            cs=source[source.trno==tn];top=cs[cs.top==0].iloc[0]
            # Summary uses actual mapped layer stock, not approximate source density.
            n60=sum(l.tn_pct*10000*m for l,m in zip(layer.itertuples(),soil_mass) if l.bottom<=60)
            c60=sum(l.soc*10000*m for l,m in zip(layer.itertuples(),soil_mass) if l.bottom<=60)
            summary.append(dict(season_id=season,trno=tn,water_level=meta.loc[tn,'water_level'],nitrogen_level=meta.loc[tn,'nitrogen_level'],
              soil_id=parsed['soil_id'],SA_factor=factors['SA'],IC_factor=factors['IC'],MF_factor=factors['MF'],
              top_TN_gkg=top.total_n_gkg,top_SOC_pct=top.organic_c_pct,top_AP_mgkg=top.available_p,top_AK_cmolkg=top.available_k,top_pH=top.ph,
              total_N_stock_0_60_kg_ha=n60,organic_C_stock_0_60_kg_ha=c60,
              initial_inorganic_N_0_100_kg_ha=initial_100,initial_inorganic_N_0_180_kg_ha=initial_total,
              native_initial_N_kg_ha=first.NIAD,fertilizer_N_expected_kg_ha=total_N_fert,native_fertilizer_N_kg_ha=last.NAPC,
              simulated_net_mineralization_kg_ha=last.NNMNC,simulated_N_uptake_kg_ha=last.NUCM,simulated_terminal_inorganic_N_kg_ha=last.NIAD,
              mapping_readback_passed=True,N_inventory_readback_passed=True))
    pd.DataFrame(summary).to_csv(OUT/'soil_nutrient_summary.csv',index=False)
    pd.DataFrame(layerrows).to_csv(OUT/'soil_layer_reconciliation.csv',index=False)
    assert all(x['unchanged'] for x in source_checks)
    spring_som=pd.read_excel(REF/'2025春/2025春土壤有机质估算与校准集.xlsx',sheet_name='25SP有机质逐样详表')
    correction=spring_som.groupby(['小区号','处理代号','土样深度'],as_index=False).agg(fc=('方案A缩放系数fc','mean'),baseline_SOC=('基准估算有机碳SOC(%)','mean'),used_SOC=('校准后有机碳SOC(%)','mean'))
    correction.to_csv(OUT/'spring_SOC_historical_corrections.csv',index=False)
    autumn=pd.read_excel(REF/'2025秋/2025秋土壤养分数据集.xlsx')
    autumn.to_csv(OUT/'autumn_raw_chemistry_with_EC.csv',index=False)
    primary_paths=[pair_path,Path(__file__),REF/'2025春/2025春初始土壤基础养分.xlsx',REF/'2025春/2025春土壤有机质估算与校准集.xlsx',
      REF/'2025秋/2025秋土壤养分数据集.xlsx',REF/'三季实验初始硝态氮铵态氮参考.xlsx']
    write(OUT/'audit_receipt.json',dict(created_at=dt.datetime.now(dt.timezone.utc).isoformat(),selected_iteration=3,selected_realization='local_00023',
      metric_definition='R2=squaredPearson,d=Willmott; terminal actual harvest pairs; leave-one-out is diagnostic, no actual exclusion',
      source_checks=source_checks,input_checks=inputs,soil_rows_verified=len(layerrows),treatments_verified=len(summary),
      measurement_or_calibration_inputs_modified=False,source_hashes={str(p.relative_to(ROOT)):sha(p) for p in primary_paths}))
    print(OUT)
    print(pd.DataFrame(metric_rows).to_string(index=False))

if __name__=='__main__':main()
