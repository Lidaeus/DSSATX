"""Freeze exact V15 s1 sources, native inputs, parameters and reference outputs."""
from pathlib import Path
import json,hashlib,zipfile,shutil,subprocess
H=Path(__file__).resolve().parent
ORIGINAL=Path('D:/Tomato_Cal/subprojects/critical_n')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf8')
def main():
    c=ORIGINAL;v=c/'n_buffer_v15';run=v/'runs/v15_s1_interface_100x2_20261028';audit=json.loads((run/'final_audit.json').read_text());trial=Path(audit['selected_replay_trial'])
    assert sha(v/'bin/v15_s1_interface.exe')==audit['binary_sha256']
    meta=json.loads((c/'n_buffer_v12/manifests/build_capacity_a.json').read_text());archive=c/'n_buffer_v12/manifests/source_capacity_a.zip';assert sha(archive)==meta['source_archive_sha256']
    assert not (H/'source').exists(),'Frozen source already exists'
    source=H/'source';source.mkdir();z=zipfile.ZipFile(archive)
    for n in z.namelist():
      dest=(source/n).resolve();assert dest.is_relative_to(source.resolve()),n
    z.extractall(source)
    overlays={n:v/'source/v15_s1_interface'/n for n in ['N_BUFFER_V2.f90','NUPTAK.for']}
    vm=json.loads((v/'build/v15_s1_interface/manifest.json').read_text())
    for n,p in overlays.items():assert sha(p)==vm['sources'][str(p)];shutil.copy2(p,source/'Plant/CROPGRO'/n)
    # All 534 inherited objects are tied to byte-identical archived source files.
    objects=[Path(x.strip().strip('"'))for x in (v/'build/v15_s1_interface/link.rsp').read_text().splitlines() if x.strip()];mapping=[]
    for p in objects:
      if '/n_buffer_v7/' in p.as_posix():
        rel=p.as_posix().split('CMakeFiles/dscsm048.dir/')[1][:-4];vendor=c/'n_buffer_v7/vendor'/rel
        assert sha(source/rel)==sha(vendor);mapping.append(dict(object=str(p),object_sha256=sha(p),source=rel,source_sha256=sha(source/rel)))
      else:
        rel='Plant/CROPGRO/'+p.name[:-4];mapping.append(dict(object=str(p),object_sha256=sha(p),source=rel,source_sha256=sha(source/rel)))
    assert len(mapping)==538
    for n in ['CROPGRO.for','GROW.for']:assert sha(source/'Plant/CROPGRO'/n)==meta['sources'][n]
    frozen=H/'frozen';frozen.mkdir();(H/'bin').mkdir();shutil.copy2(v/'bin/v15_s1_interface.exe',H/'bin/v15_s1_archived.exe')
    for name,p in {'best_parameters.csv':run/'best_parameters.csv','historical_final_audit.json':run/'final_audit.json','original_build_manifest.json':v/'build/v15_s1_interface/manifest.json','source_capacity_a_manifest.json':c/'n_buffer_v12/manifests/build_capacity_a.json'}.items():shutil.copy2(p,frozen/name)
    shutil.copy2(v/'configs/v15_s1_interface_fresh76_joint_pilot_20261028.json',frozen/'historical_design.json')
    sourcehash={str(p.relative_to(source)):sha(p)for p in source.rglob('*') if p.is_file()}
    references={};protected={str(v/'bin/v15_s1_interface.exe'):audit['binary_sha256'],str(run/'best_parameters.csv'):sha(run/'best_parameters.csv'),str(c/'bin/dscsm048_cnc.exe'):sha(c/'bin/dscsm048_cnc.exe'),'C:/DSSAT48/DSCSM048.EXE':sha('C:/DSSAT48/DSCSM048.EXE')}
    for season in ['26SP','25SP']:
      src=trial/season;dest=frozen/'native_inputs'/season;dest.mkdir(parents=True);ref=frozen/'reference'/season;ref.mkdir(parents=True)
      for p in src.iterdir():
        if not p.is_file():continue
        if p.suffix.lower() not in ['.out','.csv','.log','.exe','.json','.py']:shutil.copy2(p,dest/p.name)
        if p.suffix.lower() in ['.out','.csv']:shutil.copy2(p,ref/p.name)
      references[season]={p.name:sha(p) for p in ref.iterdir()}
    # Both historical objective and current 612-target interpretation are frozen.
    shutil.copy2(trial/'comparison.csv',frozen/'historical_comparison.csv')
    current=json.loads((c/'smoke_joint100x4_g1_r2_20261101/configs/design.json').read_text())
    shutil.copy2(current['datasets'][0]['observations'],frozen/'current_26SP_observations.csv')
    tracked={str(p.relative_to(H)):sha(p) for p in H.rglob('*') if p.is_file() and p.name not in ['freeze_manifest.json']}
    dump(H/'freeze_manifest.json',dict(version='V15-s1-stage1',baseline_sha256=audit['binary_sha256'],parameter_sha256=audit['parameter_sha256'],source_archive_sha256=sha(archive),historical_trial=str(trial),source_hashes=sourcehash,linked_source_mapping=mapping,protected=protected,reference_hashes=references,frozen_files=tracked,original_git_head=subprocess.check_output(['git','-C','D:/Tomato_Cal','rev-parse','HEAD'],text=True).strip(),branch='codex/v15-s1-baseline-20261101'))
    print('Frozen full source',len(sourcehash),'files;',len(mapping),'link objects, two native input/reference bundles',flush=True)
if __name__=='__main__':main()
