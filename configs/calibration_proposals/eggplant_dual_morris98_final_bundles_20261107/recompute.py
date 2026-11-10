import hashlib, json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

root = Path.cwd()
sys.path.insert(0, str(root/"tools/sa"))
from review_dual_spring_morris_20261105 import elementary_effects, relative
from resume_dual_spring_morris_20261105 import read
run = root/"workspace/runs/morris_dual_spring126_r40_final_bundles_sasc_default_20261107"
results = run/"results"
out = root/"configs/calibration_proposals/eggplant_dual_morris98_final_bundles_20261107"
manifest = read(run/"run_manifest.json")
result = read(results/"result_manifest.json")
assert read(run/"campaign_status.json")["status"]=="completed"
assert (result["trajectories_per_season"],result["n_parameters"],result["paired_responses"]) == (40,126,127)
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
for name,digest in result["sha256"].items():
    assert sha(results/name)==digest, name
for name,key in [("morris_X_serialized.csv","design_sha256"),("approved_bounds.csv","bounds_sha256")]:
    assert sha(run/name)==manifest[key], name

b = pd.read_csv(run/"approved_bounds.csv",float_precision="round_trip")
x = pd.read_csv(run/"morris_X_serialized.csv",index_col="point_id",float_precision="round_trip")
scores = pd.read_csv(results/"morris_process_scores.csv")
families=["phenology","canopy","biomass","yield_harvest"]
assert not scores.duplicated(["season_id","response_group","parameter"]).any()
np.testing.assert_allclose(scores.groupby(["season_id","response_group"]).group_score.sum(),1)
g = scores.pivot(index="parameter",columns=["season_id","response_group"],values="group_score")
core = g.loc[:,g.columns.get_level_values(1).isin(families)].mean(axis=1)
core26 = g.loc[:,[("26SP",k) for k in families]].mean(axis=1)
t = b.rename(columns={"name":"parameter"}).set_index("parameter")
t["core_score"] = core
t = t.sort_values(["core_score","parameter"],ascending=[False,True])
t["core_rank"] = range(1,len(t)+1)
t["core_cumulative"] = t.core_score.cumsum()
t["core_98"] = t.core_cumulative.shift(fill_value=0)<.98
t["core_26sp_score"] = core26
for season,family in g.columns:
    t[f"{season}_{family}_score"] = g[season,family]
    t[f"{season}_{family}_rank"] = g[season,family].rank(method="min",ascending=False).astype(int)

parts=[]
record_hashes={}
for season in ("25SP","26SP"):
    ds=manifest["input_bundles"][season]
    bundle=Path(ds["path"])
    metadata=pd.read_csv(bundle/"treatment_metadata.csv")
    waters=sorted(metadata.water_level.unique())
    lookup={(r.water_level,r.nitrogen_level):str(r.treatment) for r in metadata.itertuples()}
    geom=pd.read_csv(bundle/"soil_water_observations.csv")
    layers={}
    for name,q in geom[geom.phi_role.eq("soil_water_phi")].groupby("depth_label"):
        text,=q.dssat_layer_weights.unique()
        layers[name]=[(f"SW{int(j)+1}D",float(w)) for j,w in (z.split(":") for z in text.split(";"))]
    labels=[]
    rows=[]
    record_hash=hashlib.sha256()
    for i,expected in enumerate(x.to_dict("records")):
        p=run/"records"/season/f"point_{i:04d}.json"
        raw=p.read_bytes()
        record_hash.update(raw)
        r=json.loads(raw)
        assert r["status"]=="ok" and r["season"]==season and r["actual"]==expected
        d=r["diagnostics"]
        assert set(d)==set(lookup.values())
        yy={}
        if "W2" in waters:
            for n in ["N0","N1","N2","N3"]:
                yy["W2_W1",n]=d[lookup["W2",n]]["CHFPW"]-d[lookup["W1",n]]["CHFPW"]
        for w in waters:
            yy["N2_N0",w]=d[lookup[w,"N2"]]["CHFPW"]-d[lookup[w,"N0"]]["CHFPW"]
        for tn,row in d.items():
            for depth, weights in layers.items():
                yy["VWC",tn+"_"+depth]=sum(row[k]*w for k,w in weights)
            for field in ("EPAC","ESAC","NUPC","RDPD","RWAD","LN%D","SN%D"):
                yy[field,tn]=row[field]
        if not labels:
            labels=list(yy)
        assert list(yy)==labels
        rows.append(list(yy.values()))
    y=np.asarray(rows)
    assert np.isfinite(y).all()
    ee=elementary_effects(x.to_numpy(),y,(b.upper-b.lower).to_numpy())
    mu=np.abs(ee).mean(axis=0)
    for family in sorted({l[0] for l in labels}):
        ix=[i for i,l in enumerate(labels) if l[0]==family and mu[:,i].sum()>0]
        assert ix
        score=relative(mu[:,ix]).mean(axis=1)
        key=f"{season}_direct_{family}"
        v=pd.Series(score,index=b.name)
        t[key+"_score"]=v
        t[key+"_rank"]=v.rank(method="min",ascending=False).astype(int)
        for i in ix:
            vr=pd.Series(mu[:,i],index=b.name).rank(method="min",ascending=False).astype(int)
            if family in {"W2_W1","N2_N0"}:
                for j,n in enumerate(b.name):
                    parts.append(dict(season_id=season,gradient=family,context=labels[i][1],parameter=n,
                                      mu_star_kg_ha=mu[j,i],rank=vr.loc[n],n_effects=len(ee)))
    record_hashes[season]=record_hash.hexdigest()
old=read(root/"workspace/runs/eggplant_26sp_final_cal25sp_old_val_c31pst_gradient_80x4_20261106/design.json")
active=set(old["active_parameters"])
new=set(t.index[t.core_98])
supplement = {
    "YLEAF(4)": "干物质分配补充。综合第53，直接调节叶片分配。核对与固定YSTEM(4)的分配约束。",
    "RTNO3": "硝态氮吸收补充。2026春N2−N0第37，水氮交互第25。",
    "NVSMOB": "营养期相对氮动员补充。N2−N0在2026/2025春分别第41/30，与NMOBMX联合辨识需核查。",
    "RWUEP1": "水分胁迫下叶扩张补充。2026春冠层第48，W2−W1第70，属于机制优先候选。",
    "RWUMX": "单位根长最大吸水补充。2026春分层VWC第37，维持已约定的0.02–0.06候选域。",
    "PROLFF": "氮动员后的最低叶蛋白。2026春N2−N0第32，叶氮诊断第11。历史率定值超出本次Morris域，范围另审。",
}
assert len(new)==52 and len(supplement)==6 and not new.intersection(supplement)
t["previous_80x4_active"] = t.index.isin(active)
t["selection"] = np.where(t.core_98,"core_98",np.where(t.index.isin(supplement),"process_supplement","fixed_candidate"))
t["selection_note"] = t.index.to_series().map(supplement).fillna("")
t.to_csv(out/"screening_126_parameters.csv")
pd.DataFrame(parts).to_csv(out/"exact_gradient_effects.csv",index=False)
chosen=t[t.selection.ne("fixed_candidate")]
chosen[["location","core_rank","core_score","core_cumulative","lower","upper","selection","selection_note",
        "previous_80x4_active","26SP_direct_W2_W1_rank","26SP_direct_N2_N0_rank","26SP_direct_VWC_rank"]].rename(
    columns={"lower":"morris_lower","upper":"morris_upper","core_cumulative":"core_cumulative_at_rank"}
).to_csv(out/"proposed_active_parameters.csv")
coverage_fields=["core_score","26SP_direct_W2_W1_score","26SP_direct_N2_N0_score","26SP_direct_VWC_score",
                 "25SP_direct_N2_N0_score","26SP_water_nitrogen_interaction_score"]
pd.DataFrame({"core_52":t[t.core_98][coverage_fields].sum(),
              "proposed_58":chosen[coverage_fields].sum()}).to_csv(out/"coverage_by_response.csv",index_label="score")
source_files = [run/"run_manifest.json",run/"morris_X_serialized.csv",run/"approved_bounds.csv",
                results/"result_manifest.json",results/"morris_process_scores.csv",Path(__file__).resolve()]
proposal = {
    "status":"review_pending", "run_id":run.name, "core_parameters":t.index[t.core_98].tolist(),
    "supplement_parameters":list(supplement), "core_coverage":float(t.loc[t.core_98,"core_score"].sum()),
    "proposed_coverage":float(chosen.core_score.sum()),
    "source_sha256":{str(p):sha(p) for p in source_files}, "ordered_native_records_sha256":record_hashes,
    "artifact_sha256":{p.name:sha(p) for p in sorted(out.glob("*.csv"))},
}
(out/"proposal.json").write_text(json.dumps(proposal,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
print("core",len(new),"coverage",t[t.core_98].core_cumulative.iloc[-2:].to_list(),"26 count",(core26.sort_values(ascending=False).cumsum()<.98).sum()+1)
print("CORE:"," ".join(t.index[t.core_98]))
print("vs last active add",sorted(new-active),"previous not core",sorted(active-new))
cols=["core_rank","core_score","26SP_direct_W2_W1_rank","26SP_direct_N2_N0_rank","26SP_direct_VWC_rank","26SP_direct_EPAC_rank","26SP_direct_NUPC_rank","26SP_direct_RDPD_rank","26SP_direct_RWAD_rank","26SP_water_response_rank","26SP_nitrogen_response_rank","26SP_water_nitrogen_interaction_rank"]
print("NONCORE:")
print(t.loc[~t.core_98,cols].to_string())
