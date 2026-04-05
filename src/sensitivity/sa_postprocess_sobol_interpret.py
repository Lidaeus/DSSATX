
import sys

import pandas as pd

# Define file paths
sti_csv_path = r"c:\DSSAT48\Tomato_Cal\Workspace\Sensitivity_Analyze\SA_Project_Output\sen_case\sa_sen_sobol.sobol.sti.csv"
params_csv_path = r"c:\DSSAT48\Tomato_Cal\Workspace\Sensitivity_Analyze\SA_Project_Output\sen_case\sa_params.csv"

# Read STI CSV
# The file has a header like: 1->output,atop,...
# We need to handle the '->' or just standard CSV reading if the tool output was just a display format.
# Based on previous Read tool output, the file content is standard CSV. The '1->' was likely line numbers added by the Read tool.
# Let's verify if the file actually has '->' or if it was the Read tool's formatting.
# The Read tool output:
# 1→output,atop,fl-sd...
# 2→phi,0.000218963...
# This suggests the file content is:
# output,atop,fl-sd...
# phi,0.000218963...
# So standard pandas read_csv should work.

try:
    df_sti = pd.read_csv(sti_csv_path)
except Exception as e:
    print(f"Error reading STI CSV: {e}")
    sys.exit(1)

# Read Params CSV to get initial values
try:
    df_params = pd.read_csv(params_csv_path)
    # Convert parameter names to upper case for matching
    df_params['name'] = df_params['name'].str.upper().str.strip()
    param_init_map = dict(zip(df_params['name'], df_params['value']))
except Exception as e:
    print(f"Error reading Params CSV: {e}")
    sys.exit(1)

# Key indicators
indicators = {
    'Yield': 'mean_yield_hwams',
    'Biomass': 'mean_cwams',
    'LAI': 'mean_lai_auc',
    'Fruit': 'mean_fruitd_end'
}

# Filter DF for these indicators
# The column name for indicators is 'output' (based on header)
df_key = df_sti[df_sti['output'].isin(indicators.values())].copy()
df_key.set_index('output', inplace=True)

# Transpose to have parameters as rows
df_key_T = df_key.transpose()
df_key_T.index.name = 'Parameter'

# Calculate Mean STi across these 4 indicators
df_key_T['Mean_STi'] = df_key_T.mean(axis=1)

# Sort by Mean STi descending
df_ranked = df_key_T.sort_values('Mean_STi', ascending=False)

# Define parameter locations (manual mapping for now)
param_locs = {
    'XFRT': 'CUL', 'TRIFL': 'ECO', 'PM06': 'ECO', 'EM-FL': 'CUL', 'FL-SH': 'CUL', 
    'FL-SD': 'CUL', 'SD-PM': 'CUL', 'FL-LF': 'CUL', 'SFDUR': 'CUL', 'SDPDV': 'CUL', 
    'PODUR': 'CUL', 'SLAVR': 'CUL', 'SIZLF': 'CUL', 'WTPSD': 'CUL',
    'PL-EM': 'ECO', 'EM-V1': 'ECO', 'V1-JU': 'ECO', 'JU-R0': 'ECO', 'PM09': 'ECO', 
    'LNGSH': 'ECO', 'FL-VS': 'ECO', 'XMAGE': 'ECO', 'XFPHT': 'ECO', 'XFINT': 'ECO', 
    'RWDTH': 'ECO', 'RHGHT': 'ECO', 'OPTBI': 'ECO', 'SLOBI': 'ECO',
    'PARMAX': 'SPE', 'PHTMAX': 'SPE', 'KCAN': 'SPE', 'KC_SLOPE': 'SPE', 'WTFSD': 'SPE', 
    'PORPT': 'SPE', 'FRSTMF': 'SPE', 'FRLFF': 'SPE', 'ATOP': 'SPE', 'FRCNOD': 'SPE', 
    'FINREF': 'SPE', 'SLAREF': 'SPE', 'SIZREF': 'SPE', 'VSSINK': 'SPE', 'EVMODC': 'SPE',
    'TB1': 'SPE', 'TB2': 'SPE', 'TB3': 'SPE', 'TO11': 'SPE', 'TO12': 'SPE', 'TO13': 'SPE', 
    'TO22': 'SPE', 'TM2': 'SPE', 'TM3': 'SPE'
}

def get_loc(name):
    n = name.upper()
    if n.startswith('SOIL'):
        return 'SOIL'
    return param_locs.get(n, 'UNKNOWN')

# Define bounds logic (simplified version of _default_bounds)
def get_bounds(name, init, loc):
    n = name.upper()
    if loc == 'SOIL':
        if n == 'SOIL_SALB':
            return 0.05, 0.35
        # ... simplified ...
        return 0, 0
    
    if n == 'XFRT':
        return 0.6, 1.2 # Manual override or check logic
    
    # Using the logic from sa_generate_param_review_csv.py
    eco_bounds = {
        "PL-EM": (3.0, 12.0), "EM-V1": (10.0, 40.0), "JU-R0": (2.0, 20.0),
        "TRIFL": (0.20, 0.80), "RWDTH": (0.70, 1.60), "RHGHT": (0.70, 2.00),
        "XMAGE": (5.0, 30.0), "XFPHT": (5.0, 40.0), "XFINT": (0.10, 1.20)
    }
    if n in eco_bounds:
        return eco_bounds[n]
    
    temp_bounds = {
        "TB1": (8.0, 12.0), "TO11": (22.0, 28.0), "TO22": (27.0, 32.0), "TM2": (33.0, 40.0),
        "TB2": (8.0, 12.0), "TO12": (22.0, 28.0), "TB3": (8.0, 12.0), "TO13": (22.0, 28.0),
        "TM3": (33.0, 40.0)
    }
    if n in temp_bounds:
        return temp_bounds[n]
    
    if n == 'VSSINK':
        return max(0.2, 0.5 * init), max(0.2 + 0.2, 2.0 * init)
        
    if loc == 'CUL':
        return init * 0.75, init * 1.25 # Default for CUL
        
    if loc == 'SPE':
         # Default
         if 0 < init <= 1.0:
             return max(0.0, init * 0.7), min(1.0, init * 1.3)
         return init * 0.75, init * 1.25
         
    return init * 0.75, init * 1.25

# Generate Markdown Table
print("| 排名 | 参数名 | 模块 | 初始值 | 建议范围 (Min-Max) | 敏感性指数 (Total Order Mean) | 关键影响指标 |")
print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

rank = 1
for param_lower in df_ranked.index:
    param = param_lower.upper()
    # Fix parameter name if needed (e.g. fl-sd -> FL-SD)
    # The csv header used lowercase with hyphens, which matches our keys if we just upper() them.
    
    mean_sti = df_ranked.loc[param_lower, 'Mean_STi']
    
    if mean_sti < 0.01:
        continue # Skip low sensitivity
    
    loc = get_loc(param)
    init = param_init_map.get(param, 0.0)
    lb, ub = get_bounds(param, init, loc)
    
    # Identify top influencing indicator for this parameter
    # Get the row in df_key_T corresponding to this parameter
    row_vals = df_key_T.loc[param_lower]
    # Filter out Mean_STi column to find max indicator
    indicator_vals = row_vals.drop('Mean_STi')
    top_ind_code = indicator_vals.idxmax()
    # Map code back to readable name
    ind_name_map = {v: k for k, v in indicators.items()}
    top_ind = ind_name_map.get(top_ind_code, top_ind_code)
    
    # Format breakdown
    breakdown = ", ".join([f"{k}:{row_vals[v]:.2f}" for k, v in indicators.items()])
    
    print(f"| {rank} | **{param}** | {loc} | {init:.4f} | {lb:.2f} - {ub:.2f} | {mean_sti:.4f} | {top_ind} ({breakdown}) |")
    rank += 1
