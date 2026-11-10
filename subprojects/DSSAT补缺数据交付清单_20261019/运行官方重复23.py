"""Run the two explicitly requested official parameter scenarios on repeat-1 drivers."""
from pathlib import Path
import json,hashlib,shutil,subprocess,time
import pandas as pd

ROOT=Path(__file__).resolve().parent
DESIGN=json.loads((ROOT.parent/'critical_n/n_buffer_v13/configs/capacity_a_stable79_checkpointed_r4.json').read_text(encoding='utf8'))
R1=json.loads((ROOT/'原始模型输出/stable79_checkpointed150x5_20261019/last_success.json').read_text(encoding='utf8'))
TRIAL=Path(R1['trial'])
HASH='92173d5f63bc60d58839630b9a29f57632a19b373cab0faa8ad70362d98f5c7a'
SPECS=[(2,'eggplant_26sp_n012_rmse_joint65_200x5_20261012','best_calibration_parameters.csv'),
       (3,'eggplant_26sp_n012_c31_joint67_20261011','final_parameters.csv')]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')

def main():
    receipts=[]
    for rep,batch,paramname in SPECS:
        original=Path('D:/Tomato_Cal/workspace/runs')/batch
        archive=original/'selected_deterministic/_model'
        params=pd.read_csv(original/paramname)
        assert params.equals(pd.read_csv(archive/'parameters.csv'))
        assert sha(archive/'DSCSM048.EXE')==HASH==sha('C:/DSSAT48/DSCSM048.EXE')
        values=dict(zip(params.name,params.value))
        target=ROOT/f'原始模型输出/official_repeat{rep}_20261019'
        target.mkdir(exist_ok=True)
        shutil.copy2(original/paramname,target/'指定最佳参数.csv')
        receipt=dict(replicate_id=rep,scenario=batch,parameter_source=str(original/paramname),parameter_sha256=sha(original/paramname),
                     binary_source=str(archive/'DSCSM048.EXE'),binary_sha256=HASH,common_driver_source=str(TRIAL),
                     input_policy='repeat1 weather, initial conditions, management, SLPF; archived encoded genotype and own calibrated soil SLDR if present',seasons=[])
        for ds in DESIGN['datasets']:
            season=ds['season_id'];common=TRIAL/season;work=target/season
            if (work/'完成收据.json').exists():
                receipt['seasons'].append(json.loads((work/'完成收据.json').read_text(encoding='utf8')));continue
            work.mkdir(exist_ok=True)
            # Input manifest is an explicit allow-list; never copy old model outputs.
            for name in ds['native_hashes']:
                shutil.copy2(common/name,work/name)
            for suffix in ['CUL','ECO','SPE']:
                for extension in ['', '.base']:
                    name=f'TMGRO048.{suffix}{extension}'
                    shutil.copy2(archive/name,work/name)
            shutil.copy2(archive/'DSCSM048.EXE',work/'DSCSM048.EXE')
            shutil.copy2(original/paramname,work/'parameters.csv')
            if 'SOIL_SLDR' in values:
                soil=(work/'SOIL.SOL').read_text().splitlines()
                i=next(i for i,l in enumerate(soil)if l.startswith('@ SCOM'))+1
                soil[i]=soil[i][:18]+f'{values["SOIL_SLDR"]:6.3f}'+soil[i][24:]
                (work/'SOIL.SOL').write_text('\n'.join(soil)+'\n',encoding='ascii')
            checks=[]
            for name in ds['native_hashes']:
                equal=sha(common/name)==sha(work/name)
                allowed=name.startswith('TMGRO048.')or(name=='SOIL.SOL'and'SOIL_SLDR'in values)
                assert equal or allowed,(rep,season,name)
                checks.append(dict(file=name,repeat1_sha256=sha(common/name),current_sha256=sha(work/name),identical=equal,allowed_parameter_difference=allowed and not equal))
            pd.DataFrame(checks).to_csv(work/'共有输入逐文件对照.csv',index=False,encoding='utf-8-sig')
            started=time.time()
            result=subprocess.run([str(work/'DSCSM048.EXE'),'CRGRO048','B','DSSBatch.v48'],cwd=work,
                                  input='\n'*20,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                  timeout=240,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            (work/'本次运行日志.txt').write_text(result.stdout,encoding='utf8')
            assert result.returncode==0,(rep,season,result.returncode,result.stdout[-3000:])
            assert not (work/'ERROR.OUT').exists(),(work/'ERROR.OUT').read_text(errors='replace')if(work/'ERROR.OUT').exists()else''
            for name in ['ET.OUT','SoilWatBal.OUT','SoilWat.OUT','PlantGro.OUT','PlantN.OUT','FreshWt.OUT']:
                assert (work/name).stat().st_size>500
            rec=dict(replicate_id=rep,season_id=season,work=str(work),returncode=result.returncode,elapsed_seconds=round(time.time()-started,3),
                     executable_sha256=sha(work/'DSCSM048.EXE'),n_identical_manifest_inputs=sum(q['identical']for q in checks),n_manifest_inputs=len(checks),
                     modified_manifest_inputs=[q['file']for q in checks if not q['identical']],
                     actual_input_sha256={p.name:sha(p)for p in work.iterdir()if p.is_file()and(p.name in ds['native_hashes']or p.name in ['TMGRO048.CUL','TMGRO048.ECO','TMGRO048.SPE','parameters.csv','DSCSM048.EXE'])})
            dump(work/'完成收据.json',rec);receipt['seasons'].append(rec)
            print(f'Repeat {rep} {season} complete, {rec["elapsed_seconds"]} s',flush=True)
        assert sha(original/paramname)==receipt['parameter_sha256']
        dump(target/'运行收据.json',receipt);receipts.append(receipt)
    dump(ROOT/'官方重复23运行总收据.json',receipts)

if __name__=='__main__':main()
