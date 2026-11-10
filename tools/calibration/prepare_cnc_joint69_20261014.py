"""Freeze a69-parameter custom-engine successor of the all12 formal batch."""
from pathlib import Path
import datetime as dt
import json
import shutil
import subprocess
import sys
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.calibration import single_season_n as legacy

PARENT='eggplant_26sp_all12_robust_joint65_200x5_20261012'
ID='eggplant_26sp_all12_cnc_joint69_200x5_20261014'
BOUND_ID='eggplant_26sp_all12_cnc_joint69_20261014'
AUTH='参考所附自定义DSSAT资料，基于eggplant_26sp_all12_robust_joint65_200x5_20261012设置修改适配，使用自定义DSSAT正式联合率定。'
CNC={'CNC_A':(4.85,4.20,5.20),'CNC_B':(.38,.30,.45),'CNC_W0':(1.,.80,1.50),'CNC_NC_INF':(1.70,1.40,2.00)}
ATTACHMENT=Path(r'C:\Users\Lidaeus\.codex\attachments\48ce57b4-f3ed-4f24-8741-02db268fc344\已粘贴的文本.txt')

def stamp():return dt.datetime.now(dt.timezone.utc).isoformat()

def prepare(model):
    config=ROOT/'configs/runs'/ID;run=ROOT/'workspace/runs'/ID
    if config.exists() or run.exists():raise FileExistsError('Never overwrite an existing formal run')
    pc=ROOT/'configs/runs'/PARENT;pr=ROOT/'workspace/runs'/PARENT
    old=json.loads((pc/'design.json').read_text(encoding='utf-8'))
    # Parent provenance is not silently refreshed: the only preexisting drift is the added CNC species card.
    for cat in ['runtime_hashes','source_hashes']:
        for path,h in old[cat].items():
            if path=='data/templates/genotype/TMGRO048.SPE.base':continue
            if legacy.sha(ROOT/path)!=h:raise ValueError('Unreviewed parent dependency drift: '+path)
    old_spe=pr/'selected_deterministic/_model/TMGRO048.SPE.base'
    if legacy.sha(old_spe)!=old['runtime_hashes']['data/templates/genotype/TMGRO048.SPE.base']:raise ValueError('Parent species snapshot changed')
    shared=ROOT/'data/templates/genotype/TMGRO048.SPE.base';lines=shared.read_text().splitlines()
    i=next(i for i,x in enumerate(lines) if x.startswith('!*CRITICAL NITROGEN DILUTION'))
    clean=lines[:i]+lines[i+4:]
    if clean!=old_spe.read_text().splitlines():raise ValueError('Shared species changes exceed the four-line CNC card addition')
    binary=ROOT/'subprojects/critical_n/bin/dscsm048_cnc.exe'
    if binary.stat().st_size!=14936893 or legacy.sha(binary)!=model.ENGINE_SHA:raise ValueError('Attachment binary identity mismatch')
    config.mkdir(parents=True);run.mkdir(parents=True)
    (config/'engine').mkdir();(config/'templates').mkdir()
    shutil.copy2(binary,model.ENGINE);shutil.copy2(shared,model.SPE_BASE)
    shutil.copy2(ATTACHMENT,config/'user_custom_engine_reference.txt')
    frozen_parent=ROOT/'data/parameter_registry/bounds_frozen/eggplant'/(old['bounds_id']+'.csv')
    bounds=pd.read_csv(frozen_parent).fillna('')
    if legacy.sha(frozen_parent)!=old['bounds_sha256']:raise ValueError('Parent bounds changed')
    selected=legacy.runner._read_param_dict(pr/'best_calibration_parameters.csv')
    bounds['init']=bounds.name.map(selected)
    additions=[]
    for name,(initial,lower,upper) in CNC.items():
        additions.append(dict(name=name,init=initial,lower=lower,upper=upper,status='active',pargp='SPE_CNC',location='SPE',
            file='TMGRO048.SPE.base',cultivar='TM0008',ecotype='TM0001',mode='eggplant_stage2',approved=True,
            execution_enabled=True,reason='Explicit current user attachment: critical N curve parameter recommended active range'))
    bounds=pd.concat([bounds,pd.DataFrame(additions)],ignore_index=True).fillna('')
    bounds.to_csv(config/'approved_bounds_proposal.csv',index=False)
    result=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'tools/freeze_bounds.py'),'--proposal',str(config/'approved_bounds_proposal.csv'),
       '--crop','eggplant','--bounds-id',BOUND_ID,'--notes','User-authorized custom engine joint69: parent65bounds unchanged plus4active CNC; dedicated physical guards; no automatic repair'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    (run/'bounds_freeze.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    if result.returncode:raise RuntimeError('Freeze failed: '+result.stdout+result.stderr)
    frozen=frozen_parent.parent/(BOUND_ID+'.csv')
    for name in ['calibration_observations.csv','approved_objective_policy.csv','locked_evaluation_observations.csv']:
        shutil.copy2(pc/name,config/name)
    base=selected|{name:values[0] for name,values in CNC.items()}
    references={'seed_yield':base,'seed_water':base|{'RWUMX':.0105},'seed_canopy':base|{'FL-LF':180.,'SENPOR_LATE':.19}}
    for name,values in references.items():
        model.validate_parameters(values,bounds)
        pd.DataFrame(values.items(),columns=['name','value']).to_csv(run/(name+'_parameters.csv'),index=False)
    shutil.copy2(run/'seed_yield_parameters.csv',run/'initial_parameters.csv')
    runtime=dict(old['runtime_hashes']);runtime['data/templates/genotype/TMGRO048.SPE.base']=legacy.sha(shared)
    new_runtime=['src/calibration/cnc_joint_20261014.py','src/dssat/forward_cnc_joint_20261014.py',
      'tools/calibration/prepare_cnc_joint69_20261014.py','tools/calibration/launch_cnc_joint69_200x5_20261014.py',
      'subprojects/critical_n/calibration/bounds_protocol.py']
    runtime.update({p:legacy.sha(ROOT/p) for p in new_runtime})
    source_tree=ROOT/'subprojects/critical_n/dssat_csm_cnc'
    for module in ['CROPGRO','DEMAND','GROW','MOBIL','PHOTO','SENES','PODS','NUPTAK']:
        file=source_tree/'Plant/CROPGRO'/(module+'.for');runtime[str(file.relative_to(ROOT))]=legacy.sha(file)
    original=ROOT/'subprojects/critical_n/dssat_csm/Plant/CROPGRO/NUPTAK.for'
    if legacy.sha(original)!=legacy.sha(source_tree/'Plant/CROPGRO/NUPTAK.for'):raise ValueError('Native NUPTAK differs; review required')
    paths=[pc/'design.json',frozen_parent,pr/'best_calibration_parameters.csv',config/'approved_bounds_proposal.csv',
      config/'locked_evaluation_observations.csv',config/'user_custom_engine_reference.txt',model.ENGINE,model.SPE_BASE,
      run/'initial_parameters.csv',old_spe]
    d=dict(old)
    for key in ['initial_ensemble_sha256','initial_observation_ensemble_sha256']:d.pop(key,None)
    d.update(schema='formal_cnc_all12_joint_v1',design_id=ID,parent_design=str((pc/'design.json').relative_to(ROOT)),
       parent_design_sha256=legacy.sha(pc/'design.json'),proposed_bounds_id=BOUND_ID,bounds_id=BOUND_ID,bounds_sha256=legacy.sha(frozen),
       active_parameters=bounds[bounds.status=='active'].name.tolist(),active_parameter_count=69,
       dssat_executable=str(model.ENGINE),dssat_executable_sha256=model.ENGINE_SHA,status='native_preflight_pending',
       runtime_preflight_passed=False,ensemble_preflight_passed=False,
       approval=dict(user_statement=AUTH,recorded_at=stamp(),reference_sha256=legacy.sha(config/'user_custom_engine_reference.txt')),
       runtime_hashes=runtime,source_hashes={str(p.relative_to(ROOT)).replace('\\','/'):legacy.sha(p) for p in paths},
       seed=20261014,engine_scope='Pinned custom executable, private copy; no native NUPTAK modification; no production executable replacement',
       added_parameters=CNC,parameter_policy='Current user attachment recommended4active CNC overrides old subproject fixed-only protocol for this isolated batch',
       shared_template_drift_review='Only four-line critical N card addition verified against parent saved snapshot; no other drift accepted',
       parent_spe_sha256=legacy.sha(old_spe),snapshot_spe_sha256=legacy.sha(model.SPE_BASE),
       posterior_interpretation='IES optimization ensemble; CNC/genetic parameter correlation is not evidence of unique physiological identification',
       native_preflight_cases=3,native_complete_cases=0,
       preflight_scope='Custom-engine exact689targets, independent69field readback, native plant/soil N balances, followed by200members',
       initialization=old['initialization']|dict(base='parent_best_local00023_plus_CNC_defaults',reference_seeds=['seed_water','seed_canopy']),
       joint_constraints=old['joint_constraints']+['.16*(PROLFI-PROLFG)>=.002 after rounding','.16*(PROSTI-PROSTG)>=.001 after rounding','CNC_A>CNC_NC_INF>0; CNC_B/W0 positive'],
       mass_balance_checks=dict(plant_absolute_max_kg_ha=.25,soil_daily_or_cumulative_max_kg_ha=.05),
       parameter_step_handling='Reject infeasible requested/rounded F1 and old physical constraints; no projection, imputation, date shift or parameter-dependent target weights',
       initial_predictions_reused_by_IES=False)
    if d['calibration_observations_sha256']!=legacy.sha(config/'calibration_observations.csv') or d['policy_sha256']!=legacy.sha(config/'approved_objective_policy.csv'):raise ValueError('Objective changed')
    legacy.write_json(config/'design.json',d)
    results=[]
    for name in references:
        compared=model.evaluate(config/'design.json',run/(name+'_parameters.csv'),run/'preflight'/name,preflight=True)
        model.metrics(compared).to_csv(run/'preflight'/name/'family_metrics.csv',index=False)
        balance=pd.read_csv(run/'preflight'/name/'_model/nitrogen_balance_audit.csv')
        results.append(dict(seed=name,targets=len(compared),readback_fields=69,phi=float(compared.phi_contribution.sum()),
            plant_N_balance_max=float(balance.plant_residual_kg_ha.max()),soil_N_balance_max=float(balance.soil_daily_or_cumulative_max_kg_ha.max())))
        print('Custom engine reference passed:',name,flush=True)
    legacy.write_json(run/'preflight/report.json',dict(status='passed',references=results,objective_unchanged=True,engine_sha256=model.ENGINE_SHA))
    d.update(runtime_preflight_passed=True,native_complete_cases=3,status='ensemble_preflight_pending')
    legacy.write_json(config/'design.json',d)
    legacy.write_json(config/'frozen_configuration_receipt.json',dict(design_sha256=legacy.sha(config/'design.json'),recorded_at=stamp()))
    legacy.write_json(run/'approval_receipt.json',dict(user_statement=AUTH,recorded_at=stamp(),design_sha256=legacy.sha(config/'design.json')))
    legacy.write_json(run/'pipeline_status.json',dict(status='prepared',phase='ensemble_preflight_pending',updated_at=stamp()))
    model.load_design(config/'design.json')
    print('Custom69 runtime/reference preflight complete;200member preflight pending',flush=True)
