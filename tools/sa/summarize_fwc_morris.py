from __future__ import annotations
import json
from pathlib import Path
import pandas as pd


def summarize(case_dir: str):
    root = Path(case_dir)
    mio = pd.read_csv(root / 'sa_sen_morris.mio')
    mio.columns = [c.strip() for c in mio.columns]
    mio['observation_name'] = mio['observation_name'].astype(str).str.upper()
    mio['parameter_name'] = mio['parameter_name'].astype(str).str.upper()
    score_col = 'sen_mean_abs' if 'sen_mean_abs' in mio.columns else 'mu*'

    fruit = mio[mio['observation_name'].str.contains('FWC_|PDMCD_', regex=True)].copy()
    groups = {
        'fwc_only': fruit[fruit['observation_name'].str.contains('FWC_END|FWC_PEAK', regex=True)],
        'pdmcd_only': fruit[fruit['observation_name'].str.contains('PDMCD_END|PDMCD_PEAK', regex=True)],
        'fruit_water_all': fruit,
    }
    out_dir = root / 'fwc_summary'
    out_dir.mkdir(exist_ok=True)
    ranking_summary = {}
    for name, frame in groups.items():
        rank = frame.groupby('parameter_name', as_index=False)[score_col].mean().sort_values(score_col, ascending=False)
        rank.to_csv(out_dir / f'{name}_ranking.csv', index=False, encoding='utf-8-sig')
        ranking_summary[name] = rank.head(15).to_dict(orient='records')

    range_frames = []
    for name in [
        'morris_top20_fwc_end.csv',
        'morris_top20_fwc_peak.csv',
        'morris_top20_fwc_from_ratio_end.csv',
        'morris_top20_pdmcd_end.csv',
        'morris_top20_pdmcd_peak.csv',
    ]:
        path = root / 'morris_audit' / name
        if not path.is_file():
            continue
        frame = pd.read_csv(path)
        if frame.empty:
            continue
        value_col = next((col for col in frame.columns if col not in {'par', 'parameter_name'}), None)
        if value_col is None:
            continue
        metric = name.replace('morris_top20_', '').replace('.csv', '').upper()
        tmp = frame[['par', value_col]].copy()
        tmp.columns = ['parameter', 'value']
        tmp['metric'] = metric
        range_frames.append(tmp)
    selected = pd.concat(range_frames, ignore_index=True) if range_frames else pd.DataFrame(columns=['parameter', 'value', 'metric'])
    by_metric = selected.groupby('metric')['value'].agg(['min', 'max', 'mean']).reset_index() if not selected.empty else pd.DataFrame(columns=['metric', 'min', 'max', 'mean'])
    by_metric.to_csv(out_dir / 'fruit_water_metric_ranges.csv', index=False, encoding='utf-8-sig')
    by_treatment_metric = pd.DataFrame(columns=['treatment', 'metric', 'min', 'max', 'mean'])
    by_treatment_metric.to_csv(out_dir / 'fruit_water_treatment_ranges.csv', index=False, encoding='utf-8-sig')

    summary = {
        'case_dir': str(root),
        'ranking_summary': ranking_summary,
        'metric_ranges': by_metric.to_dict(orient='records'),
    }
    (out_dir / 'fwc_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    (out_dir / 'fwc_summary.md').write_text('\n'.join([
        '# FWC Morris Summary',
        '',
        '## Metric Ranges',
        '',
        by_metric.to_csv(index=False),
        '',
        '## Top Parameters (fruit_water_all)',
        '',
        pd.DataFrame(ranking_summary['fruit_water_all']).head(15).to_csv(index=False),
        ''
    ]), encoding='utf-8')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--case-dir', required=True)
    args = parser.parse_args()
    summarize(args.case_dir)
