"""Run the existing R publication suite against the frozen C23 data bundles."""
from pathlib import Path
import concurrent.futures
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'paper/07_C23_Revision_20260922'
RSCRIPT = Path('C:/Program Files/R/R-4.5.2/bin/Rscript.exe')
NOTE = 'User authorized clean C23 champion figures on 2026-09-22; scientific status unchanged.'

tasks = []
for season, selected in [('25SP', '10,13'), ('26SP', '3,12'), ('25FA', '3,9')]:
    tasks.append((season, OUT / 'paper_data' / season, OUT / 'figures' / season,
                  ['--figure-ids', 'fig3_performance,figs3_residuals,fig4_dynamics,figs4_all_treatments,fig_water_nitrogen_response',
                   '--variables', 'LAID,LWAD,SWAD,FRESH_INC', '--process-variables', 'LAID,LWAD,SWAD',
                   '--supplement-process-variables', 'LAID,LWAD,SWAD', '--treatments', selected]))
tasks.append(('main', OUT / 'paper_data/terminal', OUT / 'figures/main',
              ['--figure-ids', 'fig2_phi,fig3_performance,fig_water_nitrogen_response', '--variables', 'FRESH_CUM']))
tasks.append(('leaf_n', OUT / 'paper_data/leaf_n', OUT / 'figures/leaf_n', ['--figure-ids', 'fig_leaf_nitrogen']))
tasks.append(('ensemble', OUT / 'paper_data/ensemble', OUT / 'figures/ensemble',
              ['--figure-ids', 'figs5_posterior,figs6_spearman,figs7_equifinality']))
tasks.append(('conditional', OUT / 'paper_data/conditional', OUT / 'figures/conditional',
              ['--figure-ids', 'fig_model_performance_uncertainty,diagnostic_conditional_residual_by_treatment,fig4_dynamics_conditional,figs4_all_treatments_conditional',
               '--process-variables', 'LAID,LWAD,SWAD']))

chosen = set(sys.argv[1:])
if chosen:
    tasks = [t for t in tasks if t[0] in chosen]
logs = OUT / 'logs'
logs.mkdir(parents=True, exist_ok=True)


def render(task):
    name, src, dst, options = task
    dst.mkdir(parents=True, exist_ok=True)
    command = [str(RSCRIPT), 'paper/R/make_all.R', '--input-dir', str(src), '--out-dir', str(dst),
               *options, '--allow-unvalidated-demo', '--publication-label-note', NOTE]
    env = dict(os.environ)
    env['LC_ALL'] = 'C'
    env['LANG'] = 'en_US'
    with (logs / f'R_{name}.log').open('w', encoding='utf-8') as f:
        result = subprocess.run(command, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, env=env)
    print(f'{name}: exit {result.returncode}', flush=True)
    return dict(name=name, command=command, returncode=result.returncode)


def main():
    print("=" * 80)
    print("Rendering R Publication Figures for C23 Champion Suite")
    print("=" * 80)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(render, tasks))
    (logs / ('render_commands_' + ('_'.join(sorted(chosen)) if chosen else 'all') + '.json')).write_text(
        json.dumps(results, indent=2), encoding='utf-8'
    )
    if any(r['returncode'] != 0 for r in results):
        raise SystemExit('R render failed; inspect logs in paper/07_C23_Revision_20260922/logs/')
    print("All R publication figures rendered successfully!")


if __name__ == '__main__':
    main()
