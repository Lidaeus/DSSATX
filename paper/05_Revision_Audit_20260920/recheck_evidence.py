"""Reproduce the numerical checks for the manuscript revision; does not run DSSAT.

Outputs are editorial audit evidence, not a science_validated paper_data bundle.
Run from any directory: python <absolute path to this file>.
"""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
RUN = ROOT / 'workspace/runs/full_gen_13trt_tb1_80_95_150x6_20260920'
CASE = 'full_gen_13trt_tb1_80_95_150x6'
sources = {}


def read_csv(path):
    path = Path(path)
    sources[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return pd.read_csv(path)


def metrics(obs, sim):
    o, s = np.asarray(obs, dtype=float), np.asarray(sim, dtype=float)
    assert len(o) and np.isfinite(o).all() and np.isfinite(s).all()
    e = s - o
    sse = np.sum(e ** 2)
    sst = np.sum((o - o.mean()) ** 2)
    den = np.sum((np.abs(s - o.mean()) + np.abs(o - o.mean())) ** 2)
    rmse = np.sqrt(np.mean(e ** 2))
    return dict(n=len(o), observed_mean=o.mean(), simulated_mean=s.mean(),
                observed_sd=np.std(o, ddof=1), simulated_sd=np.std(s, ddof=1),
                rmse=rmse, mae=np.mean(np.abs(e)), bias=e.mean(),
                nrmse_pct=100 * rmse / o.mean(),
                r_squared=np.corrcoef(o, s)[0, 1] ** 2,
                nse=1 - sse / sst, d_index=1 - sse / den)


y = read_csv(ROOT / 'paper/04_References_and_Data/C15_all_35_treatments_final_yield.csv')
labels = read_csv(ROOT / 'paper/04_References_and_Data/C15_metrics_three_seasons.csv')
meta = read_csv(ROOT / 'configs/figures/treatment_metadata_xxql2501_2601_joint.csv')
assert not y.duplicated(['season', 'tn']).any() and len(y) == 35
y = y.merge(labels[['season', 'tn', 'water', 'nitro']], on=['season', 'tn'], validate='one_to_one')
y = y.merge(meta[['season_id', 'treatment', 'dataset_role']],
            left_on=['season', 'tn'], right_on=['season_id', 'treatment'],
            how='left', validate='one_to_one')
assert y.loc[y.season != '25FA', 'dataset_role'].notna().all()
y.loc[y.season == '25FA', 'dataset_role'] = 'diagnostic'
y['observed_t_ha'] = y.obs_cum_yield_kg_ha / 1000
y['simulated_t_ha'] = y.sim_cum_yield_kg_ha / 1000
y.to_csv(OUT / 'terminal_yield_with_roles.csv', index=False)

groups = [('calibration', y[y.dataset_role == 'calibration']),
          ('held_out_treatments', y[y.dataset_role == 'validation']),
          ('two_springs', y[y.season != '25FA']),
          *[(s, y[y.season == s]) for s in ['25SP', '26SP', '25FA']],
          ('all_35', y)]
yield_rows = [dict(group=g, **metrics(d.observed_t_ha, d.simulated_t_ha)) for g, d in groups]
pd.DataFrame(yield_rows).to_csv(OUT / 'terminal_yield_metrics_recomputed.csv', index=False)

contrasts = []
for (season, water), d in y[y.water != 'CK'].groupby(['season', 'water']):
    d = d.set_index('nitro')
    for lo, hi in [('N0', 'N3'), ('N0', 'N1'), ('N1', 'N2'), ('N2', 'N3')]:
        if lo not in d.index or hi not in d.index:
            continue
        og = d.loc[hi, 'observed_t_ha'] - d.loc[lo, 'observed_t_ha']
        sg = d.loc[hi, 'simulated_t_ha'] - d.loc[lo, 'simulated_t_ha']
        contrasts.append(dict(season=season, water=water, contrast=f'{hi}-{lo}',
                              observed_gap=og, simulated_gap=sg, gap_bias=sg-og))
pd.DataFrame(contrasts).to_csv(OUT / 'nitrogen_contrasts_recomputed.csv', index=False)

process_rows, events = [], []
for season in ['25SP', '26SP']:
    for kind, variables in [('process', ['LAID', 'LWAD', 'SWAD']), ('harvest', ['FRESH_INC'])]:
        path = RUN / f'c15_det_{season.lower()}' / f'c15_{season.lower()}_deterministic_{kind}_compare.csv'
        d = read_csv(path)
        assert not d.duplicated(['TN', 'DATE']).any()
        d = d.merge(meta[meta.season_id == season][['treatment', 'dataset_role']],
                    left_on='TN', right_on='treatment', validate='many_to_one')
        for role, part in d.groupby('dataset_role'):
            for v in variables:
                scale = 1000 if v == 'FRESH_INC' else 1
                vals = metrics(part[f'OBS_{v}'] / scale, part[f'SIM_{v}'] / scale)
                process_rows.append(dict(season=season, dataset_role=role, variable=v, **vals))
        if kind == 'harvest':
            events.append(dict(season=season, n_treatments=int(d.TN.nunique()),
                               n_dates=int(d.DATE.nunique()), dates=sorted(map(int, d.DATE.unique()))))
pd.DataFrame(process_rows).to_csv(OUT / 'process_metrics_recomputed.csv', index=False)

prior = read_csv(RUN / f'{CASE}.0.par.csv')
updated = read_csv(RUN / f'{CASE}.6.par.csv')
params = read_csv(ROOT / 'paper/04_References_and_Data/C15_candidate_parameters.csv').set_index('name').value
bounds = read_csv(ROOT / 'data/parameter_registry/bounds_frozen/eggplant/eggplant_full_gen_tb1_80_95_13trt_20260920.csv').set_index('name')
params.index = params.index.str.lower()
bounds.index = bounds.index.str.lower()
assert params.index.is_unique and bounds.index.is_unique
member = updated.loc[updated.real_name.astype(str) == '72'].iloc[0]
assert all(np.isclose(float(member[k]), float(v)) for k, v in params.items())
parameter_rows = []
for k, v in params.items():
    b = bounds.loc[k]
    parameter_rows.append(dict(name=k, value=v, lower=b.lower, upper=b.upper,
                              status=b.status, location=b.location,
                              at_lower=bool(np.isclose(v, b.lower, rtol=0, atol=1e-8)),
                              at_upper=bool(np.isclose(v, b.upper, rtol=0, atol=1e-8))))
pd.DataFrame(parameter_rows).to_csv(OUT / 'candidate_parameters_checked.csv', index=False)
pairs = read_csv(RUN / 'paper_data_posterior/candidate_pair_predictions.csv')
post = read_csv(RUN / 'paper_data_posterior/posterior_diagnostics.csv')
old_table = read_csv(ROOT / 'paper/02_Tables/Table1_Genetic_Parameters_Comparison.csv')
grand_mean = y.observed_t_ha.mean()
sst = ((y.observed_t_ha - grand_mean) ** 2).sum()
within = sum(((d.observed_t_ha - d.observed_t_ha.mean()) ** 2).sum() for _, d in y.groupby('season'))

hash_checks = []
for bundle in ['paper_data_c15', 'paper_data_posterior']:
    path = RUN / bundle / 'paper_data_manifest.json'
    sources[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = json.loads(path.read_text(encoding='utf-8'))
    for a in manifest['artifacts']:
        f = path.parent / a['path']
        actual = hashlib.sha256(f.read_bytes()).hexdigest()
        hash_checks.append(dict(bundle=bundle, data_status=manifest['data_status'],
                                artifact=a['path'], hash_matches=actual == a['sha256']))
pd.DataFrame(hash_checks).to_csv(OUT / 'bundle_hash_checks.csv', index=False)

facts = dict(status='editorial_audit_only_not_science_validated',
             n_prior=len(prior), n_iteration_6=len(updated),
             original_table1_rows=len(old_table), harvest_event_coverage=events,
             between_season_fraction_of_observed_sst=1-within/sst,
             tb1_diagnostics=post[post.parameter == 'TB1'].iloc[0].to_dict(),
             candidate_pairs=pairs.to_dict('records'),
             source_sha256=sources)
(OUT / 'audit_facts.json').write_text(json.dumps(facts, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(pd.DataFrame(yield_rows).round(4).to_string(index=False))
print('Between-season fraction of observed SST:', round(100*(1-within/sst), 4), '%')
print('Prior / iteration-6 rows:', len(prior), len(updated))
print('All bundle hashes match:', all(x['hash_matches'] for x in hash_checks))
print('Audit written to', OUT)
