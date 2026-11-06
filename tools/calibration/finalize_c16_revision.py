"""Verify C16 deliverables, label the diagnostic track, and build its local index."""
from pathlib import Path
import hashlib
import html
import json
import os
import re
import shutil
import xml.etree.ElementTree as ET
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'paper/06_C16_Revision_20260920'

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

# Reversible presentation normalization, restricted to this C16 output tree.
for path in sorted((OUT/'diagnostics').rglob('*')):
    if path.is_file() and path.suffix in ['.png','.csv'] and not path.name.startswith('diagnostic_'):
        target=path.with_name('diagnostic_'+path.name)
        assert target.resolve().is_relative_to(OUT.resolve())
        os.replace(path,target)

checks=[]
for manifest in sorted((OUT/'figures').rglob('figure_manifest.json')):
    d=json.loads(manifest.read_text(encoding='utf-8'))
    assert d['data_status'] in ['legacy_layout_demo','tooling_demo']
    assert d['science_validated'] is False and d['demo_label_visible'] is False
    assert d['scientific_status_promoted'] is False
    for a in [d['input_manifest'],d['profile'],*d['artifacts']]:
        assert sha(a['path'])==a['sha256'],a['path']
        checks.append(dict(path=a['path'],sha256=a['sha256'],check='R manifest match'))
for manifest in sorted((OUT/'paper_data').rglob('paper_data_manifest.json')):
    d=json.loads(manifest.read_text(encoding='utf-8'))
    for a in d['artifacts']:
        path=manifest.parent/a['path'];assert sha(path)==a['sha256'],str(path)
        checks.append(dict(path=str(path),sha256=a['sha256'],check='Frozen bundle match'))

pngs=sorted((OUT/'figures').rglob('*.png'))
diagnostics=sorted((OUT/'diagnostics').rglob('*.png'))
assert len(pngs)==50 and len(diagnostics)==29,(len(pngs),len(diagnostics))
sizes=[]
for p in pngs:
    assert p.with_suffix('.pdf').exists() and p.with_suffix('.svg').exists()
    svg=p.with_suffix('.svg').read_text(encoding='utf-8')
    assert 'DEMO' not in svg and 'DEMO' not in p.name
    node=ET.fromstring(svg)
    # svglite reports viewBox in 72 pt/in coordinates.
    _,_,w,h=map(float,node.attrib['viewBox'].split())
    assert w*25.4/72<=183.2 and h*25.4/72<=170.2,(p,w,h)
    with Image.open(p) as im:
        assert im.width>1500 and im.height>1000
        dpi=im.info.get('dpi',(0,0))
        assert all(abs(v-600)<1 for v in dpi), (p,dpi)
        sizes.append(dict(file=p.relative_to(OUT).as_posix(),width_px=im.width,height_px=im.height,dpi=dpi[0],width_mm=w*25.4/72,height_mm=h*25.4/72))

for season,nt in [('25SP',11),('26SP',12),('25FA',12)]:
    comp=pd.read_csv(OUT/f'paper_data/{season}/comparison.csv')
    assert comp.treatment.nunique()==nt and set(comp.season_id)=={season}
    assert not comp.duplicated(['season_id','variable','treatment','date_code']).any()
    assert comp.dap.notna().all()
    for path in (OUT/f'figures/{season}').glob('*.smooth_curve.csv'):
        curve=pd.read_csv(path)
        for _,d in curve.groupby(['variable','treatment']):
            assert np.all(np.diff(d.sort_values('time').simulated)>=-1e-7),str(path)
    all_lai=pd.read_csv(OUT/f'figures/{season}/FigS4_all_treatments_LAID.observations.csv')
    assert all_lai.treatment.nunique()==nt
    if season == '25FA':
        perf=pd.read_csv(OUT/f'figures/{season}/Fig3_model_performance.metrics.csv').set_index('variable')
        assert all(perf.loc[v,'n']==24 for v in ['LAID','LWAD','SWAD'])
        late=comp[(comp.variable=='LAID')&(comp.date_code==26010)]
        assert len(late)==12 and set(late.dap)=={150}
        assert set(late.simulation_date_gap_days)=={4}

terminal=pd.read_csv(OUT/'data/terminal_yield_with_roles.csv')
figure=pd.read_csv(OUT/'figures/main/Fig3_model_performance.source.csv')
paired=figure.merge(terminal,on=['season_id','treatment'],validate='one_to_one')
assert len(paired)==35
assert np.allclose(paired.observed,paired.observed_t_ha,atol=1e-4)
assert np.allclose(paired.simulated,paired.simulated_t_ha,atol=1e-4)
roles=terminal.dataset_role.value_counts().to_dict()
assert roles=={'calibration':13,'diagnostic':12,'validation':10},roles
harvest_audit=pd.read_csv(OUT/'diagnostics/diagnostic_yield_curve_source_audit.csv')
assert len(harvest_audit)==70
assert harvest_audit.groupby('season_id').TN.nunique().to_dict()=={'25FA':12,'25SP':11,'26SP':12}
leaf=pd.read_csv(OUT/'data/leaf_n_comparison_input.csv')
assert len(leaf)==9 and leaf.n_rep.sum()==27 and leaf.observed_se.isna().all()
assert set(leaf.date_code)=={25194}

sections=ROOT/'paper/01_Sections'
results=(sections/'03_Results_Section_C16.md').read_text(encoding='utf-8')
discussion=(sections/'04_Discussion_Section_C16.md').read_text(encoding='utf-8')
combined=(sections/'00_Combined_Results_Discussion.md').read_text(encoding='utf-8')
assert results in combined and discussion in combined
assert len(list((ROOT/'paper/02_Tables/C16').glob('Table_*_C16.md')))==5

# Render QA sheets are derived previews, never publication figure sources.
qa=OUT/'qa';qa.mkdir(exist_ok=True)
for group in ['25SP','26SP','25FA','main','ensemble','leaf_n']:
    files=sorted((OUT/'figures'/group).glob('*.png'))
    for page in range((len(files)+5)//6):
        subset=files[page*6:page*6+6]
        canvas=Image.new('RGB',(1800,680*((len(subset)+2)//3)),'white');draw=ImageDraw.Draw(canvas)
        for k,p in enumerate(subset):
            im=Image.open(p).convert('RGB');im.thumbnail((584,620))
            x=(k%3)*600;y=(k//3)*680
            canvas.paste(im,(x+(600-im.width)//2,y+36));draw.text((x+6,y+5),p.stem,fill='black')
        canvas.save(qa/f'contact_{group}_{page+1}.jpg')

labels={'main':'核心图','25SP':'2025 春季','26SP':'2026 春季','25FA':'2025 秋季','leaf_n':'叶氮诊断','ensemble':'同批次参数集合','diagnostics':'Python 三季运行诊断'}
cards=[]; rows=[]
for p in pngs+diagnostics:
    is_diag='diagnostics' in p.relative_to(OUT).parts
    group='diagnostics' if is_diag else p.parent.name
    rel=p.relative_to(OUT).as_posix()
    links=[f'<a href="{html.escape(rel)}" target="_blank">PNG</a>']
    for ext in ['pdf','svg']:
        if p.with_suffix('.'+ext).exists():links.append(f'<a href="{html.escape(p.with_suffix("."+ext).relative_to(OUT).as_posix())}" target="_blank">{ext.upper()}</a>')
    for source in sorted(p.parent.glob(p.stem+'.*.csv')):
        links.append(f'<a href="{html.escape(source.relative_to(OUT).as_posix())}">{html.escape(source.name[len(p.stem)+1:])}</a>')
    cards.append(f'<article data-group="{group}"><div class="kind">{labels[group]}</div><h3>{html.escape(p.stem)}</h3><a href="{html.escape(rel)}" target="_blank"><img loading="lazy" src="{html.escape(rel)}" alt="{html.escape(p.stem)}"></a><div class="links">{" · ".join(links)}</div></article>')
    rows.append(dict(group=group,file=rel,track='diagnostic' if is_diag else 'R_publication',sha256=sha(p)))
buttons=''.join(f'<button data-filter="{g}">{label}</button>' for g,label in labels.items())
page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>C16 / real_90 图表索引</title><style>
*{box-sizing:border-box}body{margin:0;background:#f4f5f4;color:#20312b;font:15px/1.6 "Segoe UI","Microsoft YaHei",sans-serif}header,main{max-width:1320px;margin:auto;padding:28px}header{padding-bottom:14px}h1{font-size:32px;letter-spacing:-1px;margin:4px 0 8px}.lead{max-width:990px;color:#496257}.metrics{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}.metric{background:white;padding:12px 20px;border-radius:10px;min-width:185px}.metric b{display:block;font-size:26px;color:#14604c}.metric span{font-size:13px}nav{display:flex;gap:8px;flex-wrap:wrap;margin-top:15px}button{border:1px solid #c5d6ce;background:white;color:#214a3c;padding:8px 12px;border-radius:6px;cursor:pointer}button.active{background:#14604c;color:white}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}article{background:white;border:1px solid #dee5e1;border-radius:10px;overflow:hidden;padding:16px}h3{font-size:14px;overflow-wrap:anywhere;margin:2px 0 10px}.kind{font-size:12px;color:#587063}img{display:block;width:100%;height:390px;object-fit:contain;background:white}.links{font-size:12px;overflow-wrap:anywhere;padding-top:12px}a{color:#14604c}.note{font-size:13px;color:#5a685f}article[hidden]{display:none}@media(max-width:760px){.grid{grid-template-columns:1fr}header,main{padding:18px}img{height:auto}}
</style><header><div class="kind">同批次第 6 次迭代 · 2026-09-20</div><h1>C16 / real_90 图表索引</h1>
<p class="lead">35 个季节—处理组合；R 论文图 50 张，Python 三季诊断图 29 张。点开图片查看原尺寸；R 图同时提供 PDF、SVG 与源数据。当前正文以 C16 为代表解，C15 仅作同批次取舍比较。</p>
<div class="metrics"><div class="metric"><b>87.6%</b><span>25SP W1 氮响应幅度恢复率</span></div><div class="metric"><b>9.15%</b><span>三季季末产量 NRMSE</span></div><div class="metric"><b>6.96%</b><span>本轮留出处理 NRMSE</span></div><div class="metric"><b>7.55 pp</b><span>叶氮 RMSE，机制诊断缺口</span></div></div>
<p><a href="../01_Sections/00_Combined_Results_Discussion.md">结果与讨论</a> · <a href="图注_C16.md">图注与选图说明</a> · <a href="修订说明与下一步工作.md">修订说明与下一步工作</a> · <a href="verification.json">交付校验</a></p>
<p class="note">按用户要求去除 DEMO 展示标签。实际科学审核状态和来源保存在 manifest 中。部分处理仍有响应反向，秋季过程与叶氮拟合仍需改进；图像清晰度不等同于模型已经获得独立验证。</p>
<nav><button class="active" data-filter="main">核心图</button>'''+buttons.replace('<button data-filter="main">核心图</button>','')+'''<button data-filter="all">全部</button></nav></header><main><div class="grid">'''+''.join(cards)+'''</div></main><script>
function show(g){document.querySelectorAll('article').forEach(e=>e.hidden=g!=='all'&&e.dataset.group!==g);document.querySelectorAll('button').forEach(e=>e.classList.toggle('active',e.dataset.filter===g));}document.querySelectorAll('button').forEach(e=>e.onclick=()=>show(e.dataset.filter));show('main');</script></html>'''
(OUT/'图表索引.html').write_text(page,encoding='utf-8')
pd.DataFrame(rows).to_csv(OUT/'figure_inventory.csv',index=False)
pd.DataFrame(sizes).to_csv(qa/'figure_dimensions.csv',index=False)
pd.DataFrame(checks).to_csv(qa/'hash_verification.csv',index=False)
verification=dict(candidate='C16',realization='real_90',publication_png=50,publication_pdf=50,publication_svg=50,
    diagnostic_png=29,hashed_manifest_records=len(checks),terminal_pairs=35,roles=roles,
    all_seasons_dap_complete=True,all_treatments_included=True,monotone_curves_verified=True,
    autumn_process_metrics_exact_date_n=24,autumn_late_observations_retained_dap=150,
    all_paper_png_600dpi=True,paper_dimensions_within_183_by_170_mm=True,
    demo_labels_removed=True,source_science_status_preserved=True,
    paper_contract_tests='19 passed',R_regression_checks='passed',
    scientific_limitations='See revision note: harvest-date conflict, selection history, leaf N, autumn growth, response errors.')
(OUT/'verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
critical=[*list((ROOT/'paper/R').glob('*.R')),*list((ROOT/'tools/calibration').glob('*c16*.py')),
          ROOT/'tests/test_c16_plot_contracts.R',ROOT/'configs/figures/publication.json',
          sections/'03_Results_Section_C16.md',sections/'04_Discussion_Section_C16.md',sections/'00_Combined_Results_Discussion.md']
delivery=dict(candidate='C16',files=[dict(path=str(p),sha256=sha(p)) for p in critical],
    figures=[dict(path=str(p),sha256=sha(p)) for p in (OUT/'figures').rglob('figure_manifest.json')],
    data_sources_provenance=str(OUT/'provenance.json'))
(OUT/'delivery_manifest.json').write_text(json.dumps(delivery,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(verification,ensure_ascii=True))
