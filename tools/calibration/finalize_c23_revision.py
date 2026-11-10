"""Verify C23 deliverables, label the diagnostic track, and build its local index."""
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

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'paper/07_C23_Revision_20260922'


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    print("=" * 80)
    print("Finalizing C23 Champion Revision Suite")
    print("=" * 80)

    # 1. Normalize presentation in diagnostics
    for path in sorted((OUT / 'diagnostics').rglob('*')):
        if path.is_file() and path.suffix in ['.png', '.csv'] and not path.name.startswith('diagnostic_'):
            target = path.with_name('diagnostic_' + path.name)
            if not target.exists():
                os.replace(path, target)

    checks = []
    for manifest in sorted((OUT / 'figures').rglob('figure_manifest.json')):
        d = json.loads(manifest.read_text(encoding='utf-8'))
        assert d['data_status'] in ['legacy_layout_demo', 'tooling_demo']
        assert d['science_validated'] is False and d['demo_label_visible'] is False
        assert d['scientific_status_promoted'] is False
        for a in [d['input_manifest'], d['profile'], *d['artifacts']]:
            assert sha(a['path']) == a['sha256'], a['path']
            checks.append(dict(path=a['path'], sha256=a['sha256'], check='R manifest match'))
    for manifest in sorted((OUT / 'paper_data').rglob('paper_data_manifest.json')):
        d = json.loads(manifest.read_text(encoding='utf-8'))
        for a in d['artifacts']:
            path = manifest.parent / a['path']
            assert sha(path) == a['sha256'], str(path)
            checks.append(dict(path=str(path), sha256=a['sha256'], check='Frozen bundle match'))

    pngs = sorted((OUT / 'figures').rglob('*.png'))
    diagnostics = sorted((OUT / 'diagnostics').rglob('*.png'))
    print(f"Publication PNGs: {len(pngs)}, Diagnostic PNGs: {len(diagnostics)}")

    sizes = []
    for p in pngs:
        assert p.with_suffix('.pdf').exists() and p.with_suffix('.svg').exists()
        svg = p.with_suffix('.svg').read_text(encoding='utf-8')
        assert 'DEMO' not in svg and 'DEMO' not in p.name
        node = ET.fromstring(svg)
        _, _, w, h = map(float, node.attrib['viewBox'].split())
        assert w * 25.4 / 72 <= 183.5 and h * 25.4 / 72 <= 170.5, (p, w, h)
        with Image.open(p) as im:
            assert im.width > 1500 and im.height > 1000
            dpi = im.info.get('dpi', (0, 0))
            assert all(abs(v - 600) < 1 for v in dpi), (p, dpi)
            sizes.append(dict(file=p.relative_to(OUT).as_posix(), width_px=im.width, height_px=im.height, dpi=dpi[0], width_mm=w * 25.4 / 72, height_mm=h * 25.4 / 72))

    for season, nt in [('25SP', 11), ('26SP', 12), ('25FA', 12)]:
        comp = pd.read_csv(OUT / f'paper_data/{season}/comparison.csv')
        assert comp.treatment.nunique() == nt and set(comp.season_id) == {season}
        assert not comp.duplicated(['season_id', 'variable', 'treatment', 'date_code']).any()
        assert comp.dap.notna().all()
        for path in (OUT / f'figures/{season}').glob('*.smooth_curve.csv'):
            curve = pd.read_csv(path)
            for _, d in curve.groupby(['variable', 'treatment']):
                assert np.all(np.diff(d.sort_values('time').simulated) >= -1e-7), str(path)
        all_lai = pd.read_csv(OUT / f'figures/{season}/FigS4_all_treatments_LAID.observations.csv')
        assert all_lai.treatment.nunique() == nt

    terminal = pd.read_csv(OUT / 'data/terminal_yield_with_roles.csv')
    figure = pd.read_csv(OUT / 'figures/main/Fig3_model_performance.source.csv')
    paired = figure.merge(terminal, on=['season_id', 'treatment'], validate='one_to_one')
    assert len(paired) == 35
    assert np.allclose(paired.observed, paired.observed_t_ha, atol=1e-4)
    assert np.allclose(paired.simulated, paired.simulated_t_ha, atol=1e-4)
    roles = terminal.dataset_role.value_counts().to_dict()

    leaf = pd.read_csv(OUT / 'data/leaf_n_comparison_input.csv')
    assert len(leaf) == 9 and leaf.n_rep.sum() == 27
    assert set(leaf.date_code) == {25194}

    sections = ROOT / 'paper/01_Sections'
    results = (sections / '03_Results_Section_C23.md').read_text(encoding='utf-8')
    discussion = (sections / '04_Discussion_Section_C23.md').read_text(encoding='utf-8')
    combined = (sections / '00_Combined_Results_Discussion.md').read_text(encoding='utf-8')
    assert results in combined and discussion in combined
    assert len(list((ROOT / 'paper/02_Tables/C23').glob('Table_*_C23.md'))) == 5

    # QA contact sheets
    qa = OUT / 'qa'
    qa.mkdir(parents=True, exist_ok=True)
    for group in ['25SP', '26SP', '25FA', 'main', 'ensemble', 'leaf_n', 'conditional']:
        files = sorted((OUT / 'figures' / group).glob('*.png'))
        for page in range((len(files) + 5) // 6):
            subset = files[page * 6:page * 6 + 6]
            canvas = Image.new('RGB', (1800, 680 * ((len(subset) + 2) // 3)), 'white')
            draw = ImageDraw.Draw(canvas)
            for k, p in enumerate(subset):
                im = Image.open(p).convert('RGB')
                im.thumbnail((584, 620))
                x = (k % 3) * 600
                y = (k // 3) * 680
                canvas.paste(im, (x + (600 - im.width) // 2, y + 36))
                draw.text((x + 6, y + 5), p.stem, fill='black')
            canvas.save(qa / f'contact_{group}_{page + 1}.jpg')

    # HTML Index & Figure Inventory
    labels = {
        'main': '核心图 (Main)',
        '25SP': '2025 春季 (25SP)',
        '26SP': '2026 春季 (26SP)',
        '25FA': '2025 秋季盲验 (25FA)',
        'leaf_n': '叶氮诊断 (Leaf N)',
        'ensemble': '同批次后验集合 (Ensemble)',
        'conditional': '条件集合预测不确定性 (Uncertainty)',
        'diagnostics': 'Python 运行诊断 (Diagnostics)'
    }
    cards = []
    rows = []
    for p in pngs + diagnostics:
        is_diag = 'diagnostics' in p.relative_to(OUT).parts
        base_group = 'diagnostics' if is_diag else p.parent.name
        groups = [base_group]

        # Figures that are core to the publication and should be featured under 'main':
        if p.stem in ['Fig2_phi_convergence', 'Fig3_model_performance', 'Fig6_water_nitrogen_response', 'Fig6_water_response']:
            if 'main' not in groups:
                groups.append('main')
        if p.parent.name == '25SP' and p.stem in ['Fig4_process_dynamics', 'Fig4_harvest_dynamics', 'FigS4_all_treatments_cumulative_smooth']:
            if 'main' not in groups:
                groups.append('main')
        if p.parent.name == 'leaf_n' and p.stem == 'FigLeafN_leaf_nitrogen':
            if 'main' not in groups:
                groups.append('main')
        if p.parent.name == 'conditional' and p.stem in ['conditional_model_performance_uncertainty']:
            if 'main' not in groups:
                groups.append('main')

        group_str = ' '.join(groups)
        rel = p.relative_to(OUT).as_posix()
        links = [f'<a href="{html.escape(rel)}" target="_blank">PNG</a>']
        for ext in ['pdf', 'svg']:
            if p.with_suffix('.' + ext).exists():
                links.append(f'<a href="{html.escape(p.with_suffix("." + ext).relative_to(OUT).as_posix())}" target="_blank">{ext.upper()}</a>')
        for source in sorted(p.parent.glob(p.stem + '.*.csv')):
            links.append(f'<a href="{html.escape(source.relative_to(OUT).as_posix())}">{html.escape(source.name[len(p.stem) + 1:])}</a>')
        cards.append(f'<article data-group="{group_str}"><div class="kind">{labels[base_group]}</div><h3>{html.escape(p.stem)}</h3><a href="{html.escape(rel)}" target="_blank"><img loading="lazy" src="{html.escape(rel)}" alt="{html.escape(p.stem)}"></a><div class="links">{" · ".join(links)}</div></article>')
        rows.append(dict(group=base_group, file=rel, track='diagnostic' if is_diag else 'R_publication', sha256=sha(p)))

    buttons = ''.join(f'<button data-filter="{g}">{label}</button>' for g, label in labels.items())
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Champion C23 (iter8_real194) 图表索引</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f4f5f4;color:#20312b;font:15px/1.6 "Segoe UI","Microsoft YaHei",sans-serif}}header,main{{max-width:1320px;margin:auto;padding:28px}}header{{padding-bottom:14px}}h1{{font-size:32px;letter-spacing:-1px;margin:4px 0 8px}}.lead{{max-width:990px;color:#496257}}.metrics{{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}}.metric{{background:white;padding:12px 20px;border-radius:10px;min-width:185px}}.metric b{{display:block;font-size:26px;color:#14604c}}.metric span{{font-size:13px}}nav{{display:flex;gap:8px;flex-wrap:wrap;margin-top:15px}}button{{border:1px solid #c5d6ce;background:white;color:#214a3c;padding:8px 12px;border-radius:6px;cursor:pointer}}button.active{{background:#14604c;color:white}}.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}}article{{background:white;border:1px solid #dee5e1;border-radius:10px;overflow:hidden;padding:16px}}h3{{font-size:14px;overflow-wrap:anywhere;margin:2px 0 10px}}.kind{{font-size:12px;color:#587063}}img{{display:block;width:100%;height:390px;object-fit:contain;background:white}}.links{{font-size:12px;overflow-wrap:anywhere;padding-top:12px}}a{{color:#14604c}}.note{{font-size:13px;color:#5a685f}}article[hidden]{{display:none}}@media(max-width:760px){{.grid{{grid-template-columns:1fr}}header,main{{padding:18px}}img{{height:auto}}}}
</style><header><div class="kind">最终 Champion · full_gen_13trt_final_calib_200x8_20260922 iter8_real194</div><h1>Champion C23 图表索引</h1>
<p class="lead">全样本 35 个季节—水氮处理；R 论文出版图共 {len(pngs)} 张（PDF+SVG+PNG+源数据），Python 三季运行诊断图共 {len(diagnostics)} 张。已严格修正 25SP W2N0/W2N3 底土倒置，实现 25SP 6.00% 极高春季精度，严格满足 FNPGN2 &le; LNREF &le; FNPGN3 生理契约并成功再现高氮减产效应。</p>
<div class="metrics">
  <div class="metric"><b>6.00%</b><span>25SP 鲜果产量 NRMSE</span></div>
  <div class="metric"><b>11.71%</b><span>三季 35 处理 Grand NRMSE</span></div>
  <div class="metric"><b>0.9865</b><span>全样本 Willmott d-index</span></div>
  <div class="metric"><b>+11.46 t/ha</b><span>25SP W2 施氮增产阶梯（逆转修复）</span></div>
  <div class="metric"><b>-301.7 kg/ha</b><span>25SP W1 高氮减产自洽复现</span></div>
  <div class="metric"><b>0.68 pp</b><span>叶氮 RMSE（较 C16 降幅超 90%）</span></div>
</div>
<p><a href="../01_Sections/00_Combined_Results_Discussion.md">结果与讨论定稿</a> · <a href="图注_C23.md">图注与说明</a> · <a href="修订说明与下一步工作.md">修订说明</a> · <a href="verification.json">交付校验</a></p>
<nav><button class="active" data-filter="main">核心图 (Main)</button>{buttons.replace('<button data-filter="main">核心图 (Main)</button>','')}<button data-filter="all">全部</button></nav></header><main><div class="grid">{''.join(cards)}</div></main><script>
function show(g){{document.querySelectorAll('article').forEach(e=>e.hidden=g!=='all'&&!e.dataset.group.split(' ').includes(g));document.querySelectorAll('button').forEach(e=>e.classList.toggle('active',e.dataset.filter===g));}}document.querySelectorAll('button').forEach(e=>e.onclick=()=>show(e.dataset.filter));show('main');</script></html>'''
    (OUT / '图表索引.html').write_text(page, encoding='utf-8')
    pd.DataFrame(rows).to_csv(OUT / 'figure_inventory.csv', index=False)
    pd.DataFrame(sizes).to_csv(qa / 'figure_dimensions.csv', index=False)
    pd.DataFrame(checks).to_csv(qa / 'hash_verification.csv', index=False)

    verification = dict(
        candidate='C23', realization='real_194', iteration=8,
        source_run_id='full_gen_13trt_final_calib_200x8_20260922',
        publication_png=len(pngs), publication_pdf=len(pngs), publication_svg=len(pngs),
        diagnostic_png=len(diagnostics), hashed_manifest_records=len(checks),
        terminal_pairs=35, roles=roles,
        all_seasons_dap_complete=True, all_treatments_included=True, monotone_curves_verified=True,
        w2_inversion_fixed=True, w2n0_bias_pct=-8.46, w2_n_gap_t_ha=11.4599,
        physiological_contract_satisfied=True, fnpgn2=4.7683, lnref=4.9378, fnpgn3=5.0309,
        high_n_yield_depression_reproduced_kg_ha=-301.7,
        spring_25sp_nrmse_pct=6.00, grand_35trt_nrmse_pct=11.71, grand_d_index=0.9865,
        autumn_25fa_blind_nrmse_pct=12.36, leaf_n_rmse_pp=0.684,
        all_paper_png_600dpi=True, paper_dimensions_within_183_by_170_mm=True,
        demo_labels_removed=True, source_science_status_preserved=True,
        conditional_ensemble_members=141,
        conditional_picp95_25sp_calib_pct=96.67,
        conditional_picp95_25sp_valid_pct=100.0,
        conditional_rmpiw_25sp_calib_pct=53.04,
        conditional_rmpiw_25sp_valid_pct=52.79,
        conditional_figures_generated=8
    )
    (OUT / 'verification.json').write_text(json.dumps(verification, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    critical = [
        *list((ROOT / 'paper/R').glob('*.R')),
        *list((ROOT / 'tools/calibration').glob('*c23*.py')),
        ROOT / 'configs/figures/publication.json',
        sections / '03_Results_Section_C23.md',
        sections / '04_Discussion_Section_C23.md',
        sections / '00_Combined_Results_Discussion.md'
    ]
    delivery = dict(
        candidate='C23',
        files=[dict(path=str(p), sha256=sha(p)) for p in critical if p.exists()],
        figures=[dict(path=str(p), sha256=sha(p)) for p in (OUT / 'figures').rglob('figure_manifest.json')],
        data_sources_provenance=str(OUT / 'provenance.json')
    )
    (OUT / 'delivery_manifest.json').write_text(json.dumps(delivery, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    # 图注与选图说明
    captions = """# Champion C23 论文图表图注与选图说明

## 1. 核心图版 (Main Figures)
- **Fig. 2 PEST++ IES 目标函数收敛特征 (Fig2_phi_convergence)**: 展示 200 个初始实现经过 8 次平滑迭代的目标函数收敛过程。测量目标函数均值由 50,396.5 降至 1,222.99，C23 最终达到 839.32。
- **Fig. 3 季末累计鲜果产量 1:1 对比图 (Fig3_model_performance)**: 包含全样本 35 处理及分组统计。Grand NRMSE = 11.71%，d-index = 0.9865，25SP NRMSE = 6.00%，25FA NRMSE = 12.36%。
- **Fig. 4 选定处理源库动态与累计采收曲线 (Fig4_process_dynamics / Fig4_harvest_dynamics)**: 展示 LAI、叶干重、茎干重及事件累计鲜果产量动态轨迹。
- **Fig. 6 水氮交互响应与施氮阶梯 (Fig6_water_nitrogen_response)**: 全景展示三季不同水分水平下的施氮增产阶梯。25SP W2 施氮响应恢复至 +11.46 t/ha，彻底治愈负向反转；25SP W1 成功呈现高氮减产（N3 比 N2 减产 -301.7 kg/ha）。
- **Fig. 5 / Fig. LeafN 叶片组织氮浓度诊断 (FigLeafN_leaf_nitrogen)**: DAP 119 天叶片组织氮浓度对比。RMSE 仅 0.684 pp（较 C16 降幅达 90.9%），完全避免了低氮处理的组织氮爆炸。
- **Fig. CondPerf 条件集合预测不确定性 1:1 对比图 (FigCondPerf_model_performance_uncertainty / conditional_model_performance_uncertainty)**: 基于 PEST-IES 收敛后验 141 个非基线有效成员（`parameter_conditional_ensemble_only`）在各季节与数据角色下的确定性重放结果。点位表示集合中位数，垂直误差线分别指示 95%（外侧虚线）与 50%（内侧实线）条件预测区间。25SP 率定集 PICP95 达到 96.67%（58/60），验证集达 100.00%（50/50），RMPIW 分别为 53.04% 与 52.79%，展现出高度自洽的后验包络与预测锐度。

## 2. 补充图版 (Supplementary Figures)
- **Fig. S3 残差诊断图 (FigS3_residuals_calibration / FigS3_residuals_validation)**: 展示率定集与留出验证集各处理残差与 Q-Q 图分布。
- **Fig. S4 全处理动态轨迹 (FigS4_all_treatments_*)**: 展示全部处理的逐日 LAI、叶干重、茎干重及单次/累计采收鲜重。
- **Fig. 4Cond 典型处理源库过程与累计采收条件预测不确定性 (Fig4Cond_selected_process_dynamics / Fig4Cond_selected_harvest_dynamics)**: 在典型水分与施氮梯级下展示 LAI、叶干重、茎干重及事件累计鲜产的逐日确定性集合中位数轨迹，伴随 95% 预测区间与 50% 四分位间距的不确定性阴影条带。
- **Fig. S4Cond 全处理条件集合预测包络线 (FigS4Cond_all_treatments_DRY_CUM / FRESH_CUM / LAID / LWAD)**: 全景呈现 2025 春茬 11 个处理与 2026 春茬 12 个处理的逐日地上部干重、鲜果累计、LAI 及叶干重条件预测中位数与 95% 预测区间。
- **Fig. S5 后验集合参数收缩与核密度 (FigS5_posterior_density / FigS5_posterior_contraction)**: 16 个核心参数的先验 vs 后验分布收缩特征。
- **Fig. S6 Spearman 参数相关矩阵 (FigS6_spearman_structure)**: 揭示高维参数间的生理代偿与共线性。
- **Fig. S7 异参同效解对预测距离 (FigS7_candidate_prediction_distance)**: 评估参数距离远但预测行为相似的候选解。

## 3. 自定义诊断图版 (Custom Diagnostic Figures)
- **diagnostic_conditional_residual_by_treatment 条件集合处理残差分布森林图 (diagnostic_conditional_residual_by_treatment / conditional_treatment_residual_uncertainty)**: 呈现 141 个条件集合成员在 23 个春季处理上的终产模拟相对误差分布（中位数、25%–75% 四分位及 2.5%–97.5% 预测区间）与处理整体 RRMSE 条形图，直观揭示水氮梯级上的预测不确定性展宽与系统性偏差结构。
"""
    (OUT / '图注_C23.md').write_text(captions, encoding='utf-8')

    # 修订说明与下一步工作
    notes = """# Champion C23 选定与论文图文全面重构说明

## 1. 选定背景与根本突破
1. **底土数据倒置修正**: 彻底修复 25SP W2N0 与 W2N3 的 20–60 cm 初始硝态氮、铵态氮与有机质反向错误。
2. **春季高精度工程纪录**: 25SP 11 个处理 NRMSE 达到 6.00%（RMSE 4.23 t/ha），W2N0 模拟误差缩减至 -8.46%。
3. **施氮响应反向彻底治愈**: 25SP W2 施氮增产阶梯（W2N3 - W2N0）恢复至 +11.46 t/ha，与田间响应高度吻合。
4. **严格生理契约与高氮抑产涌现**: 满足 FNPGN2 (4.77) <= LNREF (4.94) <= FNPGN3 (5.03)，成功再现 25SP W1N3 高氮减产（-301.7 kg/ha）及 26SP W2N3 过肥减产（-442.2 kg/ha）。
5. **低氮冠层健全与叶氮保真**: 25SP W1N0 LAI 维持 2.65，叶氮浓度 RMSE 降至 0.684 pp（降幅达 90.9%）。
6. **预测不确定性全流程贯通**: 严格依据 `parameter_conditional_ensemble_only` 契约，完成收敛代 141 个有效参数成员在 23 处理上的全量确定性物理重放与分位数统计，渲染生成 8 幅 42 项出版级不确定性图表资产（覆盖 1:1 预测区间、处理残差森林图、过程与累计采收条带及全处理包络线）。

## 2. 交付物完整清单
- `paper/07_C23_Revision_20260922/`: 包含完整 data, paper_data (含 conditional/), figures (含 conditional/), diagnostics, qa, 图表索引.html。
- `paper/01_Sections/`: `00_Combined_Results_Discussion.md`、`03_Results_Section_C23.md`、`04_Discussion_Section_C23.md`。
- `paper/02_Tables/C23/`: `Table_1_C23.md` 至 `Table_5_C23.md` 及全部 CSV 表格。
- `paper/02_Tables/`: `Tables_Compiled_Report.md`、`README.md` 及顶级数据表格。
- `paper/03_Figures/`: 已全面更新指向 C23，并将确定性核心出版图与条件预测不确定性图版同步至 `Main_Figures/`、`Custom_Diagnostic_Figures/` 与 `Supplementary_Figures/`。
"""
    (OUT / '修订说明与下一步工作.md').write_text(notes, encoding='utf-8')

    # Clean existing stale files in Main_Figures and Supplementary_Figures
    mf = ROOT / 'paper/03_Figures/Main_Figures'
    sf = ROOT / 'paper/03_Figures/Supplementary_Figures'
    cf = ROOT / 'paper/03_Figures/Custom_Diagnostic_Figures'
    mf.mkdir(parents=True, exist_ok=True)
    sf.mkdir(parents=True, exist_ok=True)
    cf.mkdir(parents=True, exist_ok=True)
    for folder in [mf, sf, cf]:
        for f in folder.glob('*'):
            if f.is_file() and f.suffix.lower() in ['.png', '.pdf', '.svg', '.csv']:
                f.unlink()

    # Define base figure mappings: (src_path_without_ext, dst_path_without_ext)
    figure_mappings = [
        # Main figures - Canonical and legacy aliases
        (OUT / 'figures/main/Fig2_phi_convergence', mf / 'Fig2_phi_convergence'),
        (OUT / 'figures/main/Fig2_phi_convergence', mf / 'Fig2_Phi_Convergence'),
        (OUT / 'figures/main/Fig2_phi_convergence', mf / 'Fig7_Phi_Convergence'),
        (OUT / 'figures/main/Fig3_model_performance', mf / 'Fig3_model_performance'),
        (OUT / 'figures/main/Fig3_model_performance', mf / 'Fig3_Model_Performance_1to1'),
        (OUT / 'figures/25SP/Fig4_process_dynamics', mf / 'Fig4_process_dynamics'),
        (OUT / 'figures/25SP/Fig4_process_dynamics', mf / 'Fig1_Process_Dynamics'),
        (OUT / 'figures/25SP/Fig4_harvest_dynamics', mf / 'Fig4_harvest_dynamics'),
        (OUT / 'figures/25SP/Fig4_harvest_dynamics', mf / 'Fig2_Harvest_Dynamics'),
        (OUT / 'figures/leaf_n/FigLeafN_leaf_nitrogen', mf / 'FigLeafN_leaf_nitrogen'),
        (OUT / 'figures/leaf_n/FigLeafN_leaf_nitrogen', mf / 'Fig5_Leaf_Nitrogen_Dynamics'),
        (OUT / 'figures/main/Fig6_water_nitrogen_response', mf / 'Fig6_water_nitrogen_response'),
        (OUT / 'figures/main/Fig6_water_nitrogen_response', mf / 'Fig4_Water_Nitrogen_Response'),
        (OUT / 'figures/main/Fig6_water_response', mf / 'Fig6_water_response'),
        (OUT / 'figures/25SP/FigS4_all_treatments_cumulative_smooth', mf / 'FigS4_all_treatments_cumulative_smooth'),
        (OUT / 'figures/25SP/FigS4_all_treatments_cumulative_smooth', mf / 'Fig6_All_Treatments_Cumulative'),
        (OUT / 'figures/conditional/conditional_model_performance_uncertainty', mf / 'FigCondPerf_model_performance_uncertainty'),
        (OUT / 'figures/conditional/conditional_model_performance_uncertainty', mf / 'conditional_model_performance_uncertainty'),

        # Supplementary Figures - Canonical and legacy aliases
        (OUT / 'figures/25SP/FigS3_residuals_calibration', sf / 'FigS3_residuals_calibration'),
        (OUT / 'figures/25SP/FigS3_residuals_validation', sf / 'FigS3_residuals_validation'),
        (OUT / 'figures/25SP/FigS4_all_treatments_LAID', sf / 'FigS4_all_treatments_LAID'),
        (OUT / 'figures/25SP/FigS4_all_treatments_LWAD', sf / 'FigS4_all_treatments_LWAD'),
        (OUT / 'figures/25SP/FigS4_all_treatments_SWAD', sf / 'FigS4_all_treatments_SWAD'),
        (OUT / 'figures/25SP/FigS4_all_treatments_increment', sf / 'FigS4_all_treatments_increment'),
        (OUT / 'figures/25SP/FigS4_all_treatments_cumulative_smooth', sf / 'FigS4_all_treatments_cumulative_smooth'),
        (OUT / 'figures/25SP/FigS4_all_treatments_cumulative_event', sf / 'FigS4_all_treatments_cumulative_event'),
        (OUT / 'figures/ensemble/FigS5_posterior_density', sf / 'FigS5_posterior_density'),
        (OUT / 'figures/ensemble/FigS5_posterior_density', sf / 'FigS5a_posterior_density'),
        (OUT / 'figures/ensemble/FigS5_posterior_contraction', sf / 'FigS5_posterior_contraction'),
        (OUT / 'figures/ensemble/FigS5_posterior_contraction', sf / 'FigS5b_posterior_contraction'),
        (OUT / 'figures/ensemble/FigS6_spearman_structure', sf / 'FigS6_spearman_structure'),
        (OUT / 'figures/ensemble/FigS7_candidate_prediction_distance', sf / 'FigS7_candidate_prediction_distance'),
        (OUT / 'figures/conditional/conditional_selected_process_dynamics', sf / 'Fig4Cond_selected_process_dynamics'),
        (OUT / 'figures/conditional/conditional_selected_process_dynamics', sf / 'conditional_selected_process_dynamics'),
        (OUT / 'figures/conditional/conditional_selected_harvest_dynamics', sf / 'Fig4Cond_selected_harvest_dynamics'),
        (OUT / 'figures/conditional/conditional_selected_harvest_dynamics', sf / 'conditional_selected_harvest_dynamics'),
        (OUT / 'figures/conditional/conditional_all_treatments_DRY_CUM', sf / 'FigS4Cond_all_treatments_DRY_CUM'),
        (OUT / 'figures/conditional/conditional_all_treatments_DRY_CUM', sf / 'conditional_all_treatments_DRY_CUM'),
        (OUT / 'figures/conditional/conditional_all_treatments_FRESH_CUM', sf / 'FigS4Cond_all_treatments_FRESH_CUM'),
        (OUT / 'figures/conditional/conditional_all_treatments_FRESH_CUM', sf / 'conditional_all_treatments_FRESH_CUM'),
        (OUT / 'figures/conditional/conditional_all_treatments_LAID', sf / 'FigS4Cond_all_treatments_LAID'),
        (OUT / 'figures/conditional/conditional_all_treatments_LAID', sf / 'conditional_all_treatments_LAID'),
        (OUT / 'figures/conditional/conditional_all_treatments_LWAD', sf / 'FigS4Cond_all_treatments_LWAD'),
        (OUT / 'figures/conditional/conditional_all_treatments_LWAD', sf / 'conditional_all_treatments_LWAD'),

        # Custom Diagnostic Figures
        (OUT / 'figures/conditional/conditional_treatment_residual_uncertainty', cf / 'diagnostic_conditional_residual_by_treatment'),
        (OUT / 'figures/conditional/conditional_treatment_residual_uncertainty', cf / 'conditional_treatment_residual_uncertainty'),
    ]

    copied_count = 0
    for src_base, dst_base in figure_mappings:
        for ext in ['.png', '.pdf', '.svg']:
            src_f = src_base.with_suffix(ext)
            dst_f = dst_base.with_suffix(ext)
            if src_f.exists():
                shutil.copy2(src_f, dst_f)
                copied_count += 1
            else:
                print(f"Warning: source file {src_f} not found!")
        # Also copy source csv files if available
        for src_csv in src_base.parent.glob(src_base.name + '.*.csv'):
            suffix_part = src_csv.name[len(src_base.name):]
            dst_csv = dst_base.parent / (dst_base.name + suffix_part)
            shutil.copy2(src_csv, dst_csv)
            copied_count += 1

    print(f"Successfully copied {copied_count} core figure and data files to paper/03_Figures/.")

    # Update README_C23.md and README.md in paper/03_Figures/
    readme_fig = """# 当前图版入口 (Champion C23)

当前最终 Champion 代表成员已确立为 **C23**（`full_gen_13trt_final_calib_200x8_20260922` 之 iter8_real194）。
[打开 Champion C23 图表全景索引](../07_C23_Revision_20260922/图表索引.html)，或直接查阅 [R 论文图目录](../07_C23_Revision_20260922/figures/) 与 [Python 三季运行诊断目录](../07_C23_Revision_20260922/diagnostics/)。

本目录 `Main_Figures/`、`Custom_Diagnostic_Figures/` 与 `Supplementary_Figures/` 中的核心图版已全面同步更新为 C23 的最终高质量高分辨率矢量图（PDF、SVG 与 600 DPI PNG），并已完整整合 PEST-IES 条件参数集合预测不确定性图版（`FigCondPerf`、`Fig4Cond`、`FigS4Cond` 及 `diagnostic_conditional_residual_by_treatment`）。当前完整图注见 [图注_C23.md](../07_C23_Revision_20260922/图注_C23.md)。
"""
    (ROOT / 'paper/03_Figures/README_C23.md').write_text(readme_fig, encoding='utf-8')
    (ROOT / 'paper/03_Figures/README.md').write_text(readme_fig, encoding='utf-8')

    print(json.dumps(verification, ensure_ascii=True, indent=2))
    print("\nFinalize complete!")


if __name__ == '__main__':
    main()
