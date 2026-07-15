"""Extract baseline simulated values from existing pest run for pwtadj1.

Uses regex to parse the PEST .rei file since column widths vary
between simple and time-series observations.
"""
import re

rei_path = "d:/Tomato_Cal/workspace/eggplant_stage2_v14_full.0.base.rei"
output_path = "d:/Tomato_Cal/workspace/eggplant_stage2_v14_full.noptmax0_sims.csv"

obs_data = []
line_num = 0
with open(rei_path, 'r', encoding='utf-8') as f:
    for line in f:
        line_num += 1
        line = line.rstrip()
        if len(line) < 10:
            continue

        measured_str = re.search(r'([+-]?\d+\.\d+)\s{2,}', line)
        if not measured_str:
            continue

        measured_start = measured_str.start()
        measured_val = measured_str.group(1)

        rest = line[measured_start:].strip()
        parts = rest.split()

        if len(parts) < 4:
            continue

        try:
            measured = float(parts[0])
            modelled = float(parts[1])
            residual = float(parts[2])
            weight = float(parts[3])
        except ValueError:
            continue

        name_end = measured_start
        name_and_group = line[:name_end].strip()
        name_match = re.match(r'([^\s]+)\s+(.+)', name_and_group)
        if not name_match:
            continue

        obs_name = name_match.group(1)
        group_name = name_match.group(2)

        obs_data.append({
            'obsnme': obs_name,
            'simulated': modelled,
            'obgnme': group_name
        })

import pandas as pd
df = pd.DataFrame(obs_data)
df.to_csv(output_path, index=False)
print(f"Extracted {len(df)} observations to {output_path}")
print(f"\nFirst 5 rows:")
print(df.head().to_string())
print(f"\nUnique groups ({len(df['obgnme'].unique())} total):")
for g in sorted(df['obgnme'].unique()):
    count = len(df[df['obgnme'] == g])
    sample_obs = df[df['obgnme'] == g]['obsnme'].iloc[0] if count > 0 else ''
    print(f"  [{g}]: {count} obs  (e.g. {sample_obs})")
