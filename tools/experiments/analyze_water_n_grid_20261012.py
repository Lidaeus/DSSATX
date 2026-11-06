"""Exact-observation-date process/response audit of isolated diagnostic grids."""
from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.calibration.single_season_n import read_native

OUT=ROOT/"workspace/experiments/joint67_water_n_diagnosis_20261012"


def main():
    manifest=json.loads((OUT/"experiment_manifest.json").read_text(encoding="utf-8"))
    obs=pd.read_csv(ROOT/"configs/calibration_proposals/eggplant_26sp_n012_review_20261011/observation_catalog.csv")
    rows=[];pairs=[];quality=[];stocks=[]
    for dataset in manifest["datasets"]:
        season=dataset["season_id"]
        treatments=dataset["roles"].get("calibration",dataset["roles"].get("validation"))
        md=pd.read_csv(ROOT/dataset["bundle_path"]/"treatment_metadata.csv").set_index("treatment")
        observed=obs[(obs.season_id==season)&obs.variable.eq("CHFPW")&obs.trno.isin(treatments)].sort_values("date").groupby("trno").tail(1).set_index("trno")
        for case in manifest["cases"]:
            work=OUT/"cases"/case["case_id"]/season
            if not (work/"process_summary.csv").exists():continue
            frames={k:read_native(work/f"{k}.OUT") for k in ["PlantGro","SoilWat","SoilNi","FreshWt"]}
            etfile=next(f for f in work.glob("*.OUT") if "ETAC" in f.read_text(encoding="latin1",errors="replace")[:6000])
            frames["ET"]=read_native(etfile)
            summary=pd.read_csv(work/"process_summary.csv").set_index("trno")
            # Initial soil state in FileX is before the first integration;
            # this avoids first-day loss/whole-profile rounding in SoilWat.
            soil=[];insoil=False
            for line in (work/"SOIL.SOL").read_text().splitlines():
                if line.startswith('@  SLB'):insoil=True;continue
                if line.startswith('*') or line.startswith('@'):insoil=False
                if insoil and line.split() and line.split()[0].isdigit():soil.append(list(map(float,line.split())))
            soilmap={int(x[0]):x for x in soil};ic={};section=""
            for line in (work/(dataset["experiment_code"]+".TMX")).read_text().splitlines():
                if line.startswith('*'):section=line.strip()
                parts=line.split()
                if section=='*INITIAL CONDITIONS' and len(parts)==5 and parts[0].isdigit() and parts[1].isdigit():
                    ic[(int(parts[0]),int(parts[1]))]=list(map(float,parts[2:]))
            current={}
            for tn in treatments:
                date=observed.loc[tn,"date"];g=frames["PlantGro"].loc[tn].loc[:date];w=frames["SoilWat"].loc[tn].loc[:date]
                n=frames["SoilNi"].loc[tn].loc[:date];e=frames["ET"].loc[tn].loc[:date];f=frames["FreshWt"].loc[(tn,date)]
                row=summary.loc[tn].to_dict();row.update(season_id=season,trno=tn,date=date,
                    water_level=md.loc[tn,"water_level"],nitrogen_level=md.loc[tn,"nitrogen_level"],
                    observed_fresh=float(observed.loc[tn,"observed"]),final_fresh=float(f.CHFPW),final_dry=float(f.CHPDT),
                    final_SWTD=float(w.SWTD.iloc[-1]),irrigation=float(w.IRRC.iloc[-1]),rain=float(w.PREC.iloc[-1]),
                    drainage=float(w.DRNC.iloc[-1]),runoff=float(w.ROFC.iloc[-1]),
                    final_mineral_N=float(n.NIAD.iloc[-1]),fertilizer_N=float(n.NAPC.iloc[-1]),
                    net_mineralization=float(n.NNMNC.iloc[-1]),uptake_N=float(n.NUCM.iloc[-1]),leached_N=float(n.NLCC.iloc[-1]),
                    ET=float(e.ETAC.iloc[-1]),transpiration=float(e.EPAC.iloc[-1]),evaporation=float(e.ESAC.iloc[-1]),potential_ET=float(e.EOAC.iloc[-1]),
                    mean_WSPD=float(g.WSPD.mean()),mean_WSGD=float(g.WSGD.mean()),mean_NSTD=float(g.NSTD.mean()))
                prev=0;mm=0;minn=0;paw60=0;paw100=0;wet60=0
                for depth,data in soilmap.items():
                    dl=depth-prev;prev=depth;sw,nh4,no3=ic[(tn,depth)]
                    mm+=sw*dl*10;minn+=(nh4+no3)*data[7]*dl*.1
                    if depth<=60:paw60+=max(0,sw-data[2])*dl*10;wet60+=sw*dl*10
                    if depth<=100:paw100+=max(0,sw-data[2])*dl*10
                row.update(initial_water_exact=mm,initial_N_exact=minn,initial_PAW60=paw60,initial_PAW100=paw100,initial_water60=wet60,
                           ET_balance_residual=mm+row['irrigation']+row['rain']-row['drainage']-row['runoff']-row['final_SWTD']-row['ET'])
                rows.append(row);current[tn]=row
                if case['case_id']=='baseline':stocks.append(row)
            response={};n_adj=[];water=[]
            for wlevel in ('W1','W2','W3'):
                members={md.loc[tn,'nitrogen_level']:tn for tn in treatments if md.loc[tn,'water_level']==wlevel}
                for high,low in [('N1','N0'),('N2','N1'),('N2','N0')]:
                    if high in members and low in members:
                        h,l=current[members[high]],current[members[low]]
                        target=h['observed_fresh']-l['observed_fresh'];sim=h['final_fresh']-l['final_fresh']
                        pairs.append(dict(case_id=case['case_id'],family=case['family'],season_id=season,type='N',stratum=wlevel,contrast=high+'-'+low,observed=target,simulated=sim))
                        if (high,low)==('N2','N1'):n_adj.append((target,sim))
            for nlevel in ('N0','N1','N2','N3'):
                members={md.loc[tn,'water_level']:tn for tn in treatments if md.loc[tn,'nitrogen_level']==nlevel}
                for high in ('W2','W3'):
                    if high in members and 'W1' in members:
                        h,l=current[members[high]],current[members['W1']]
                        target=h['observed_fresh']-l['observed_fresh'];sim=h['final_fresh']-l['final_fresh']
                        pairs.append(dict(case_id=case['case_id'],family=case['family'],season_id=season,type='W',stratum=nlevel,contrast=high+'-W1',observed=target,simulated=sim))
                        if nlevel in ('N1','N2'):water.append((target,sim))
            q=dict(**case,season_id=season,n_treatments=len(treatments),fresh_terminal_nrmse=100*np.sqrt(np.mean([(x['final_fresh']-x['observed_fresh'])**2 for x in current.values()]))/np.mean([x['observed_fresh'] for x in current.values()]),
                   W_positive_pairs=sum(sim>0 for target,sim in water),W_pairs=len(water),
                   W_nrmse=100*np.sqrt(np.mean([(sim-target)**2 for target,sim in water]))/np.mean([target for target,sim in water]) if water else np.nan,
                   N_adjacent_nrmse=100*np.sqrt(np.mean([(sim-target)**2 for target,sim in n_adj]))/np.mean([target for target,sim in n_adj]) if n_adj else np.nan)
            if season=='26SP':
                comp=pd.read_csv(work/'calibration_diagnostic_comparison.csv');q['missing_primary_targets']=int(comp.simulated.isna().sum())
                q['full_phi']=float(np.square((comp.simulated-comp.observed)*comp.final_weight).sum()) if not q['missing_primary_targets'] else np.nan
                for variable in ['LAID','LWAD','SWAD','CHTD','LEAF_N_PCT','STEM_N_PCT','FRUIT_N_PCT','VWC','CHPDT','HPODW']:
                    part=comp[comp.variable.eq(variable)]
                    q[variable+'_nrmse']=100*np.sqrt(np.mean(np.square(part.simulated-part.observed)))/part.observed.mean() if part.simulated.notna().all() else np.nan
            quality.append(q)
    pd.DataFrame(rows).to_csv(OUT/'exact_date_process_grid.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(pairs).to_csv(OUT/'response_grid.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(quality).to_csv(OUT/'case_metrics.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(stocks).to_csv(OUT/'baseline_process_and_stocks.csv',index=False,encoding='utf-8-sig')
    print('Exact-date process and complete-Phi audit saved:',len(quality),'season/case results')


if __name__=='__main__':main()
