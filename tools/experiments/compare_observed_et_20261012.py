"""Read-only interval ET/water-balance audit; no calibration or new runs."""
from pathlib import Path
import hashlib
import json
import re
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.calibration.single_season_n import read_native

GRID = ROOT / 'workspace/experiments/joint67_water_n_diagnosis_20261012'
OUT = ROOT / 'workspace/audits/observed_et_comparison_20261012'
IMAGE = Path('C:/Users/Lidaeus/AppData/Local/Temp/codex-clipboard-d6f1f57b-193c-4ca2-af41-95b062383962.png')

# Means and treatment SD transcribed from the user-supplied Tables 3 and 4.
# Means of marginal water groups are NOT substituted for individual treatments.
OBS = {
 '26SP': {
  'N0_W1': [(107.84,11.46),(201.49,11.64),(309.32,21.04)],
  'N0_W2': [(111.63,16.82),(299.98,15.88),(411.61,10.55)],
  'N0_W3': [(103.91,14.65),(367.34,13.73),(471.25,15.77)],
  'N1_W1': [(126.24,22.88),(188.38,8.70),(314.62,14.37)],
  'N1_W2': [(125.21,15.03),(267.17,6.12),(392.37,8.96)],
  'N1_W3': [(119.98,6.58),(363.11,9.61),(483.09,16.17)],
  'N2_W1': [(119.34,0.04),(170.34,6.11),(289.68,6.14)],
  'N2_W2': [(139.21,15.39),(255.50,13.93),(394.70,17.33)],
  'N2_W3': [(119.83,20.26),(373.98,20.27),(493.81,14.42)],
  'N3_W1': [(118.05,20.30),(162.16,28.18),(280.21,14.47)],
  'N3_W2': [(119.86,20.50),(266.24,13.20),(386.10,25.38)],
  'N3_W3': [(124.51,31.01),(408.86,22.53),(533.37,18.30)],
 },
 '25SP': {
  'N0_W1': [(182.88,13.14),(43.62,16.90),(80.25,21.39),(306.76,22.36)],
  'N0_W3': [(186.31,12.38),(78.56,8.52),(182.04,16.64),(446.71,13.67)],
  'N1_W1': [(178.95,10.70),(63.42,8.24),(54.71,4.26),(297.08,11.90)],
  'N1_W3': [(183.09,13.67),(74.22,1.06),(206.17,7.40),(463.48,21.73)],
  'N2_W1': [(192.07,13.21),(66.06,22.36),(69.89,23.86),(328.02,35.20)],
  'N2_W3': [(188.83,13.42),(75.55,13.17),(186.79,24.61),(451.12,11.92)],
  'N3_W1': [(156.47,22.57),(51.89,3.28),(66.74,9.46),(275.11,24.08)],
  'N3_W3': [(162.54,13.47),(94.15,11.71),(196.01,27.18),(452.71,10.16)],
 },
}
WINDOWS = {
 '26SP': [('early','2026-03-14','2026-05-02'),('late','2026-05-02','2026-07-17'),('total','2026-03-14','2026-07-17')],
 '25SP': [('early','2025-03-12','2025-05-01'),('middle','2025-05-01','2025-05-24'),('late','2025-05-24','2025-07-12'),('total','2025-03-12','2025-07-12')],
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((GRID/'experiment_manifest.json').read_text(encoding='utf-8'))
    observations = []
    for season, treatments in OBS.items():
        for treatment, values in treatments.items():
            nitrogen, water = treatment.split('_')
            for (phase, start, end), (mean, sd) in zip(WINDOWS[season], values):
                observations.append(dict(season_id=season, nitrogen_level=nitrogen,water_level=water,phase=phase,
                    start=start,end=end,days=(pd.Timestamp(end)-pd.Timestamp(start)).days,
                    observed_ET=mean,observed_sd=sd,n_rep=3,
                    window_status='user_confirmed_dates' if season=='26SP' else 'explicit_in_user_table',
                    source='user_Table_3' if season=='26SP' else 'user_Table_4',
                    measurement_method='I-minus-delta-storage-0to100cm; rain/runoff/drainage assumed zero'))
    observed = pd.DataFrame(observations)
    assert len(observed)==68
    sum_checks=[]
    for season, values in OBS.items():
        for treatment, v in values.items():
            phase_sum=sum(x[0] for x in v[:-1]); difference=phase_sum-v[-1][0]
            sum_checks.append(dict(season_id=season,treatment=treatment,phase_sum=phase_sum,reported_total=v[-1][0],difference=difference,
                status='small_table_nonclosure_review' if abs(difference)>0.02001 else 'rounding_consistent'))
    pd.DataFrame(sum_checks).to_csv(OUT/'table_sum_checks.csv',index=False,encoding='utf-8-sig')
    observed.to_csv(OUT/'observed_ET_transcription.csv',index=False,encoding='utf-8-sig')
    rows=[]; sources={}
    for dataset in manifest['datasets']:
        season=dataset['season_id']
        if season not in OBS: continue
        metadata=pd.read_csv(ROOT/dataset['bundle_path']/'treatment_metadata.csv').set_index('treatment')
        for case in manifest['cases']:
            work=GRID/'cases'/case['case_id']/season
            et=read_native(work/'ET.OUT'); soil=read_native(work/'SoilWat.OUT')
            layer_header=next(x for x in (work/'SoilWat.OUT').read_text().splitlines() if '0-5' in x)
            layers=[tuple(map(int,x)) for x in re.findall(r'(\d+)-(\d+)',layer_header)]
            assert layers[0][0]==0 and layers[-1][1]==180
            assert all(layers[i][1]==layers[i+1][0] for i in range(len(layers)-1))
            assert any(bottom==100 for top,bottom in layers)
            def stock100(record):
                return sum(float(record[f'SW{i+1}D'])*(bottom-top)*10 for i,(top,bottom) in enumerate(layers) if bottom<=100)
            for file in [work/'ET.OUT',work/'SoilWat.OUT']:
                sources[str(file.relative_to(ROOT))]=hashlib.sha256(file.read_bytes()).hexdigest()
            for tn in et.index.get_level_values('trno').unique():
                md=metadata.loc[tn]; lookup=observed[(observed.season_id==season)&(observed.water_level==md.water_level)&(observed.nitrogen_level==md.nitrogen_level)]
                for ob in lookup.to_dict('records'):
                    # A storage sampling date denotes a boundary, not two included days.
                    # Morning-boundary approximation retains Mar14 irrigation AFTER sampling.
                    a=(pd.Timestamp(ob['start'])-pd.Timedelta(days=1)).strftime('%Y-%m-%d')
                    b=(pd.Timestamp(ob['end'])-pd.Timedelta(days=1)).strftime('%Y-%m-%d')
                    ea,eb=et.loc[(tn,a)],et.loc[(tn,b)];sa,sb=soil.loc[(tn,a)],soil.loc[(tn,b)]
                    evening_a,evening_b=et.loc[(tn,ob['start'])],et.loc[(tn,ob['end'])]
                    evening_sa,evening_sb=soil.loc[(tn,ob['start'])],soil.loc[(tn,ob['end'])]
                    daily=et.loc[tn].loc[(et.loc[tn].index>a)&(et.loc[tn].index<=b)]
                    assert len(daily)==ob['days'],(season,tn,a,b)
                    delta=lambda column:float(eb[column]-ea[column])
                    sd=lambda column:float(sb[column]-sa[column])
                    ET=delta('ETAC'); transp=delta('EPAC');evap=delta('ESAC');EO=delta('EOAC')
                    assert abs(ET-transp-evap)<.031
                    assert abs(ET-float(daily.ETAA.sum()))<.03
                    apparent=sd('IRRC')+sd('PREC')-sd('ROFC')-sd('SWTD')
                    ds100=stock100(sb)-stock100(sa)
                    apparent100=sd('IRRC')+sd('PREC')-sd('ROFC')-ds100
                    rows.append(dict(**ob,case_id=case['case_id'],family=case['family'],trno=int(tn),
                        RWUMX=case.get('RWUMX'),KEP=case.get('KEP'),simulated_ET=ET,simulated_transpiration=transp,
                        simulated_evaporation=evap,simulated_potential_ET=EO,simulated_drainage=sd('DRNC'),
                        irrigation=sd('IRRC'),storage_change=sd('SWTD'),rain=sd('PREC'),runoff=sd('ROFC'),
                        apparent_full_profile_no_drainage=apparent,
                        storage_change100=ds100,apparent_100cm_no_drainage=apparent100,
                        apparent100_residual=apparent100-ob['observed_ET'],
                        unresolved_100cm_balance_minus_true_ET=apparent100-ET,
                        balance_rounding_residual=apparent-sd('DRNC')-ET,
                        mean_SRAD=float(daily.SRAA.mean()),sum_SRAD=float(daily.SRAA.sum()),
                        residual=ET-ob['observed_ET'],relative_bias=100*(ET/ob['observed_ET']-1),
                        evening_boundary_ET=float(evening_b.ETAC-evening_a.ETAC),
                        evening_boundary_apparent100=float(evening_sb.IRRC-evening_sa.IRRC-stock100(evening_sb)+stock100(evening_sa))))
    comparison=pd.DataFrame(rows)
    comparison.to_csv(OUT/'interval_ET_comparison_all_grid.csv',index=False,encoding='utf-8-sig')
    comparison[comparison.case_id.eq('baseline')].to_csv(OUT/'baseline_ET_comparison.csv',index=False,encoding='utf-8-sig')
    water=comparison.groupby(['case_id','season_id','phase','water_level'],as_index=False).agg(
        n_treatments=('trno','size'),observed_ET=('observed_ET','mean'),simulated_ET=('simulated_ET','mean'),
        transpiration=('simulated_transpiration','mean'),evaporation=('simulated_evaporation','mean'),potential_ET=('simulated_potential_ET','mean'),
        drainage=('simulated_drainage','mean'),apparent_full_profile_no_drainage=('apparent_full_profile_no_drainage','mean'),
        apparent_100cm_no_drainage=('apparent_100cm_no_drainage','mean'),
        irrigation=('irrigation','mean'),storage_change=('storage_change','mean'))
    water.to_csv(OUT/'water_group_interval_comparison.csv',index=False,encoding='utf-8-sig')
    quality=[]
    for (case,season,phase), q in comparison.groupby(['case_id','season_id','phase']):
        quality.append(dict(case_id=case,season_id=season,phase=phase,n=len(q),observed_mean=q.observed_ET.mean(),
            simulated_mean=q.simulated_ET.mean(),RMSE=np.sqrt(np.mean(np.square(q.residual))),
            NRMSE=100*np.sqrt(np.mean(np.square(q.residual)))/q.observed_ET.mean(),
            bias=q.residual.mean(),mean_relative_bias=100*(q.simulated_ET.mean()/q.observed_ET.mean()-1)))
        quality[-1].update(apparent100_mean=q.apparent_100cm_no_drainage.mean(),
            apparent100_NRMSE=100*np.sqrt(np.mean(np.square(q.apparent100_residual)))/q.observed_ET.mean(),
            apparent100_bias=q.apparent100_residual.mean())
    pd.DataFrame(quality).to_csv(OUT/'interval_ET_metrics.csv',index=False,encoding='utf-8-sig')
    contrasts=[]
    for (case,season,phase,nitrogen), q in comparison.groupby(['case_id','season_id','phase','nitrogen_level']):
        q=q.set_index('water_level')
        for high in ['W2','W3']:
            if high not in q.index:continue
            contrasts.append(dict(case_id=case,season_id=season,phase=phase,nitrogen_level=nitrogen,contrast=high+'-W1',
                observed=q.loc[high,'observed_ET']-q.loc['W1','observed_ET'],simulated=q.loc[high,'simulated_ET']-q.loc['W1','simulated_ET'],
                transpiration=q.loc[high,'simulated_transpiration']-q.loc['W1','simulated_transpiration'],
                evaporation=q.loc[high,'simulated_evaporation']-q.loc['W1','simulated_evaporation']))
            contrasts[-1].update(apparent100=q.loc[high,'apparent_100cm_no_drainage']-q.loc['W1','apparent_100cm_no_drainage'])
    pd.DataFrame(contrasts).to_csv(OUT/'interval_ET_water_contrasts.csv',index=False,encoding='utf-8-sig')
    receipt=dict(status='diagnostic_only_not_formal_calibration',
        image_sha256=hashlib.sha256(IMAGE.read_bytes()).hexdigest(),
        image_name=IMAGE.name,script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        provisional_2026_dates=False,measurement_method_pending=False,
        user_confirmation='2026 Mar14-May2-Jul17; both-season rain/runoff/drainage set zero, 1m water balance; deep percolation may not be zero',
        convention='Primary [start,end) morning approximation, using cumulative(end-1)-cumulative(start-1); evening (start,end] sensitivity also exported',
        n_source_treatment_interval_rows=len(observed),n_matched_baseline_rows=int(comparison.case_id.eq('baseline').sum()),
        n_grid_cases=int(comparison.case_id.nunique()),n_comparison_rows=len(comparison),
        max_ET_balance_rounding_residual_mm=float(comparison.balance_rounding_residual.abs().max()),
        source_sha256=sources,formal_inputs_changed=False,new_simulations=False,
        caveats=['Exact endpoint sampling hours unknown except Mar14 sampled before irrigation; daily boundary sensitivity exported',
            'Reported ET is apparent 1m balance with deep percolation set zero, not independent measured true ET',
            'SD is repeat SD, not SE; phase/total/daily ET not independent targets',
            '2026 N3 not simulated in existing grid; group means use N0-N2 only',
            '2025 used only for retrospective external diagnostics, not selecting optimal parameters',
            'No drainage cannot be presumed; full 180cm profile residual is not equivalent to a shallower observed balance'])
    (OUT/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:receipt[k] for k in ['n_source_treatment_interval_rows','n_matched_baseline_rows','n_grid_cases','n_comparison_rows','max_ET_balance_rounding_residual_mm']},indent=2))
    print(water[(water.case_id=='baseline')].to_string(index=False))
    print(pd.DataFrame(quality).query("case_id in ['baseline','water_k0.85_r0.012','water_k0.85_r0.008','water_k0.85_r0.020']").to_string(index=False))


if __name__=='__main__':main()
