"""Read-only trace replay of the actual calibrated best; independent C1-C4 audits."""
from pathlib import Path
import json,runpy,sys
import replay_readiness as replay
from smoke_forward import dump,sha

ROOT=replay.CN/'runs/n4864_C4_joint80x4_20261103_r2'
OUT=replay.CN/'reports/C3_C4_diagnostics_and_calibration_20261103/final_verification'
if __name__=='__main__':
    d=json.loads((ROOT/'design.json').read_text(encoding='utf8'))
    c=json.loads((ROOT/'completion_receipt.json').read_text(encoding='utf8'))
    source=Path(c['best_trial']);exe=Path(d['binary'])
    inputs=[p.name for p in Path(d['inputs']).iterdir()if p.is_file()]
    replay.OUT=OUT
    result=replay.run('best_trace',source,exe,inputs,ROOT/'design.json')
    assert result['phi']==c['best_actual_phi']
    work=OUT/'cases/best_trace'
    sys.path.insert(0,str(replay.REPO/'research/n_v3'))
    import workflow
    from prepare_readiness import numeric_records,COMPARE_FILES
    checks={f:numeric_records(source/f)==numeric_records(work/f)for f in COMPARE_FILES}
    assert all(checks.values()),checks
    inputs_equal={f:sha(source/f)==sha(work/f)for f in inputs+['NIntegration.nml']if f!='DSSATPRO.v48'}
    assert all(inputs_equal.values())
    workflow.OUT=OUT
    for script in ['verify_c4.py','verify_c4_photo.py','verify_c1.py','verify_c2.py','verify_c3.py']:
        sys.argv=[script,'best_trace'];runpy.run_path(str(replay.REPO/'research/n_v3'/script),run_name='__main__')
    dump(OUT/'calibrated_best_verification.json',dict(passed=True,binary_sha256=sha(exe),
        phi=result['phi'],P0_trace_does_not_change_native_outputs=checks,actual_inputs_equal=inputs_equal,
        independent_C1_C2_C3_C4_and_canopy_checks=True,whole_elemental_C_closed=False))
