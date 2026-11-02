"""Freeze exact delivered configuration, executable identity and evidence."""
import json,shutil,subprocess
from workflow import OUT,CN,REPO,sha,dump

exe=OUT/'bin/delivery/dscsm048_delivery.exe'
build=json.loads((exe.parent/'build_receipt.json').read_text(encoding='utf8'))
assert sha(exe)==build['sha256']
assert all(sha(REPO/name)==h for name,h in build['sources'].items())
assert subprocess.check_output(['git','status','--porcelain'],cwd=REPO,text=True)==''
subprocess.run(['git','merge-base','--is-ancestor','25c93b9a2f73f8ec45bf441b198dac5fb7b22849','HEAD'],cwd=REPO,check=True)
protected=json.loads((CN/'reports/n_integration_v2_readiness_20261102/baseline_verified/readiness_receipt.json').read_text(encoding='utf8'))['protected_executables_before']
assert all(sha(path)==h for path,h in protected.items())
protected[str(CN/'reports/A_budget_feedback_20261102/bin/dscsm048_4864_A_verified.exe')]='a54fe3c3ff12eb7c8ccb90a7782beb7744835a8cf901dc661b5342080beaef39'
assert all(sha(path)==h for path,h in protected.items())
config=OUT/'NIntegration_C1_C2_C3_research.nml'
shutil.copy2(OUT/'cases/delivery_combined/NIntegration.nml',config)
cases=['delivery_mode0','delivery_A','delivery_C1','delivery_C2','delivery_C3','delivery_combined','delivery_repeat',
       'delivery_lowC_C3','delivery_lowC_combined','delivery_veryLowC_combined','delivery_combined_nogate']
receipts={}
for name in cases:
    path=OUT/'cases'/name/'receipt.json';r=json.loads(path.read_text(encoding='utf8'))
    assert r['success'] and r['binary_sha256']==sha(exe)
    receipts[name]=dict(receipt_sha256=sha(path),phi=r.get('phi'),objective_error=r.get('objective_error'),budget=r.get('budget'))
report=OUT/'C0-C3分阶段实施与验证报告_20261103.md'
assert report.is_file()
evidence={str(p.relative_to(OUT)):sha(p)for p in OUT.glob('*.json') if p.name!='delivery_manifest.json'}
evidence.update({str(p.relative_to(OUT)):sha(p)for p in OUT.glob('delivery_*.csv')})
dump(OUT/'delivery_manifest.json',dict(status='C0_C3_engineering_complete_not_management_validated',date='2026-11-03',
    git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
    branch=subprocess.check_output(['git','branch','--show-current'],cwd=REPO,text=True).strip(),source_worktree=str(REPO),
    source_worktree_clean=True,source_hashes=build['sources'],binary=str(exe),binary_sha256=sha(exe),
    build_receipt_sha256=sha(exe.parent/'build_receipt.json'),configuration=str(config),configuration_sha256=sha(config),
    report=str(report),report_sha256=sha(report),protected_executables_unchanged=protected,cases=receipts,evidence=evidence,
    observations_and_weights_changed=False,calibration_executed=False,whole_elemental_C_closed=False,
    C4_physiology_implemented=False,C4_accounting_design=str(REPO/'research/n_v3/C4_accounting_design.md'),
    adopted_V15_principles_approved='2026-11-03; V1-V3 adaptations; existing-site V2 response; no old-file replacement',
    fixed_experimental_settings=dict(remob_tau=10,protect_beta=.7,slow_ratio=3),
    severity_state='shared smoothed C1 growth state; raw vegetative state diagnostic only'))
print('PASS: 11 delivered native cases; source hashes match committed code; 5 protected executables unchanged; exact tested NML frozen.')
