"""Freeze C4 evidence only; never replace a production executable."""
import json,shutil,subprocess
from workflow import OUT,CN,REPO,sha,dump
from run_c4_delivery import specs,PREVIOUS

exe=OUT/'bin/delivery/dscsm048_delivery.exe'
build=json.loads((exe.parent/'build_receipt.json').read_text(encoding='utf8'))
assert sha(exe)==build['sha256']
assert all(sha(REPO/name)==h for name,h in build['sources'].items())
assert subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True)==''
subprocess.run(['git','merge-base','--is-ancestor','25c93b9a2f73f8ec45bf441b198dac5fb7b22849','HEAD'],cwd=REPO,check=True)
protected=json.loads((CN/'reports/n_integration_v2_readiness_20261102/baseline_verified/readiness_receipt.json').read_text(encoding='utf8'))['protected_executables_before']
protected[str(CN/'reports/A_budget_feedback_20261102/bin/dscsm048_4864_A_verified.exe')]='a54fe3c3ff12eb7c8ccb90a7782beb7744835a8cf901dc661b5342080beaef39'
old=json.loads((PREVIOUS/'delivery_manifest.json').read_text(encoding='utf8'))
protected[old['binary']]=old['binary_sha256']
assert all(sha(path)==h for path,h in protected.items())
config=OUT/'NIntegration_C4_research.nml'
shutil.copy2(OUT/'cases/delivery_full/NIntegration.nml',config)
receipts={}
for name,_,_ in specs():
    p=OUT/'cases'/name/'receipt.json';r=json.loads(p.read_text(encoding='utf8'))
    assert r['success'] and r['binary_sha256']==sha(exe)
    assert (OUT/'cases'/name/'comparison.csv').is_file() and 'objective_error' not in r
    receipts[name]=dict(receipt_sha256=sha(p),input_role=r['input_role'],phi=r.get('phi'),budget=r.get('budget'))
required=['C4_regression_checks.json','C4_verification_delivery_stock.json',
    'C4_photo_verification_delivery_photo.json','C1_state_verification_delivery_full.json',
    'C2_verification_delivery_C3.json','C3_verification_delivery_full.json']
for name in required:assert (OUT/name).is_file(),name
report=OUT/'C4叶片耦合_预算修复与固定参数消融报告_20261103.md'
assert report.is_file()
evidence={str(p.relative_to(OUT)):sha(p)for pattern in ['C4*.json','C4*.csv','C1*.json','C2*.json','C3*.json'] for p in OUT.glob(pattern)}
evidence['units/c4_final/receipt.json']=sha(OUT/'units/c4_final/receipt.json')
dump(OUT/'delivery_manifest.json',dict(
    status='C4_engineering_candidate_scientific_acceptance_partial_not_promoted',date='2026-11-03',
    git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
    mechanism_build_commit=build['git_head'],branch=subprocess.check_output(['git','branch','--show-current'],cwd=REPO,text=True).strip(),
    source_worktree=str(REPO),source_worktree_clean=True,source_hashes=build['sources'],
    binary=str(exe),binary_sha256=sha(exe),build_receipt_sha256=sha(exe.parent/'build_receipt.json'),
    configuration=str(config),configuration_sha256=sha(config),report=str(report),report_sha256=sha(report),
    protected_executables_unchanged=protected,cases=receipts,evidence=evidence,
    observations_and_weights_changed=False,calibration_executed=False,
    whole_elemental_C_closed=False,actual_CH2O_payment_closed=True,
    added_N_senescence_default=0,unpaid_maintenance_is_diagnostic_not_mortality=True,
    frozen_C3_manifest=str(PREVIOUS/'delivery_manifest.json'),
    next_gate='C4 chemical-C composition audit; C5 controlled gradient/recovery/pulse/load experiments before calibration'))
print('PASS: 12 same-binary cases, committed source hashes, six protected executables unchanged; C4 remains a research candidate.')
