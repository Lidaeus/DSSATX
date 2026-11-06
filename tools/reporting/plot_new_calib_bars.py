import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import os

df = pd.read_csv('workspace/experiments/compare_real81_and_optionb/new_calib_35_treatments_compare.csv')

out_dirs = [
    'C:/Users/Lidaeus/.gemini/antigravity-cli/brain/06a22b3d-1374-436c-944f-90bd22502f7f/images',
    'workspace/experiments/compare_real81_and_optionb',
    'paper/03_Figures'
]
for d in out_dirs:
    os.makedirs(d, exist_ok=True)

plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
fig, axes = plt.subplots(3, 1, figsize=(14, 13), dpi=300)

seasons = [
    ('25SP', '2025 Spring Season (25SP, 11 Treatments, SLPF=0.88, SLU1=2.5mm, SLDR=0.40)', axes[0]),
    ('26SP', '2026 Spring Season (26SP, 12 Treatments, SLPF=0.89, SLU1=2.5mm, SLDR=0.40)', axes[1]),
    ('25FA', '2025 Autumn Blind Validation (25FA, 12 Treatments, SLU1=2.5mm, SLDR=0.40)', axes[2])
]

colors = {
    'Obs': '#222222',
    'Real80': '#1b9e77',    # Teal green (Champion)
    'Real159': '#d95f02',   # Orange (Runner-up)
    'OrigReal81': '#7570b3' # Purple (Orig Real 81)
}

for season_code, title, ax in seasons:
    sub = df[df['SEASON'] == season_code].copy()
    n_trt = len(sub)
    x = np.arange(n_trt)
    width = 0.20
    
    ax.bar(x - 1.5*width, sub['OBS_t_ha'], width, label='Observed', color=colors['Obs'], alpha=0.9, edgecolor='black', zorder=3)
    ax.bar(x - 0.5*width, sub['SIM_New_Real80_t_ha'], width, label='New Champion Real 80 (Grand NRMSE: 9.41%)', color=colors['Real80'], alpha=0.85, zorder=3)
    ax.bar(x + 0.5*width, sub['SIM_New_Real159_t_ha'], width, label='New Real 159 (Grand NRMSE: 9.99%)', color=colors['Real159'], alpha=0.85, zorder=3)
    ax.bar(x + 1.5*width, sub['SIM_OrigReal81_NewSoil_t_ha'], width, label='Orig Real 81 (Updated Soil)', color=colors['OrigReal81'], alpha=0.85, zorder=3)
    
    x_labels = [f"{row['Trt_Label']}\n(TN{row['TN']})" for _, row in sub.iterrows()]
    ax.set_xticks(x)
    ax.set_xticklabels(x_labels, fontsize=9.5)
    ax.set_title(title, fontsize=12, fontweight='bold', pad=8)
    ax.set_ylabel('Fresh Fruit Yield (t/ha)', fontsize=10.5)
    
    if season_code == '25FA':
        ax.set_ylim(0, 24)
    else:
        ax.set_ylim(45, 88)
        
    ax.grid(True, linestyle='--', alpha=0.5, axis='y', zorder=0)
    if season_code == '25SP':
        ax.legend(loc='upper right', ncol=4, fontsize=9, framealpha=0.9)

plt.tight_layout()
fig_name = 'diagnostic_new_calib_treatment_bars.png'
for d in out_dirs:
    plt.savefig(os.path.join(d, fig_name), dpi=300)
plt.close()
print('Successfully generated diagnostic_new_calib_treatment_bars.png')
