import os
import pandas as pd
import pyemu

# File Paths
WORKSPACE = r"C:\DSSAT48\Tomato_Cal\Workspace"
CUL_BASE_FILE = os.path.join(WORKSPACE, "TMGRO048.CUL.base")
CUL_FILE = os.path.join(WORKSPACE, "TMGRO048.CUL")
OUT_FILE = os.path.join(WORKSPACE, "Evaluate.OUT")
PARAM_CSV_TPL = os.path.join(WORKSPACE, "pest_params.csv.tpl")
PARAM_CSV = os.path.join(WORKSPACE, "pest_params.csv")
INS_FILE = os.path.join(WORKSPACE, "Evaluate.OUT.ins")
PST_FILE = os.path.join(WORKSPACE, "tomato_cal.pst")

def parse_cul_params():
    """
    Parses TMGRO048.CUL.base to extract adjustable parameters based on flags.
    """
    with open(CUL_BASE_FILE, 'r') as f:
        lines = f.readlines()

    header_idx = -1
    calib_idx = -1
    min_idx = -1
    max_idx = -1
    tm0001_idx = -1

    for i, line in enumerate(lines):
        if line.startswith("@VAR#"):
            header_idx = i
        elif line.startswith("!Calibration"):
            calib_idx = i
        elif "MINIMA" in line:
            min_idx = i
        elif "MAXIMA" in line:
            max_idx = i
        elif line.startswith("TM0001"):
            tm0001_idx = i

    if any(idx == -1 for idx in [header_idx, calib_idx, min_idx, max_idx, tm0001_idx]):
        raise ValueError("Could not find all required sections in TMGRO048.CUL.base")

    headers = lines[header_idx].split()
    param_names = headers[4:] 
    
    calib_flags = lines[calib_idx].split()[1:]
    min_vals = lines[min_idx].split()[4:]
    max_vals = lines[max_idx].split()[4:]
    
    # TM0001 Florida 47 2010 Cal . TM0001 12.33
    # 0      1       2  3    4   5 6      7
    init_vals = lines[tm0001_idx].split()[7:] 
    
    params = []
    
    for i, name in enumerate(param_names):
        if i < len(calib_flags):
            flag = calib_flags[i]
            if flag in ['P', 'G']: # Adjustable
                p_min = float(min_vals[i])
                p_max = float(max_vals[i])
                p_init = float(init_vals[i])
                
                # Determine status
                status = "none" # adjustable
                if p_min == p_max:
                    status = "fixed"
                
                params.append({
                    "name": name,
                    "init": p_init,
                    "lower": p_min,
                    "upper": p_max,
                    "idx": i,
                    "status": status
                })
    
    return params, lines, tm0001_idx

def create_param_csv_tpl(params):
    """
    Creates pest_params.csv.tpl
    Format:
    ptf ~
    name,value
    par1,~  par1  ~
    ...
    """
    with open(PARAM_CSV_TPL, 'w') as f:
        f.write("ptf ~\n")
        f.write("name,value\n")
        for p in params:
            f.write(f"{p['name']},~ {p['name']} ~\n")

def create_ins_and_pst(params):
    # Read Evaluate.OUT
    try:
        df = pd.read_csv(OUT_FILE, sep='\s+', skiprows=2)
    except Exception as e:
        print(f"Warning: Could not read Evaluate.OUT: {e}. Creating dummy INS.")
        # Create a dummy INS if file doesn't exist, but we need structure.
        # Assuming we know the structure or file exists from previous run.
        return

    # Identify observation columns (ending in M)
    obs_cols = [c for c in df.columns if c.endswith('M')]
    sim_cols = [c[:-1]+'S' for c in obs_cols] 
    
    # Phenology columns that should be tracked even if missing (weight=0)
    CRITICAL_OBS = ['ADAPM', 'MDAPM', 'PD1PM']
    
    # Correction for PEST token counting vs Pandas columns
    # Empirical evidence shows variable offsets due to column splitting:
    # ADAPS (7) -> Needs Offset 1
    # PWAMS (19) -> Needs Offset 4
    # CWAMS (23) -> Needs Offset 5
    def get_pest_offset(col_idx):
        if col_idx < 15: return 1
        if col_idx < 21: return 4
        return 5

    obs_data = []
    ins_lines = ["pif @"]
    ins_lines.append(f"l3") 
    
    for idx, row in df.iterrows():
        run_no = int(row['@RUN'])
        current_ins_line = "l1 "
        
        col_names = df.columns.tolist()
        valid_obs = []
        for obs_col, sim_col in zip(obs_cols, sim_cols):
            val = row[obs_col]
            # Add if valid OR if it is a critical phenology metric
            if val != -99 or obs_col in CRITICAL_OBS:
                valid_obs.append((obs_col, sim_col, val))
        
        if not valid_obs:
            ins_lines.append(current_ins_line)
            continue
            
        valid_obs.sort(key=lambda x: col_names.index(x[1]))
        
        last_idx = -1
        for obs_col, sim_col, val in valid_obs:
            col_idx = col_names.index(sim_col)
            target_idx = col_idx + get_pest_offset(col_idx)
            skips = target_idx - last_idx - 1
            if skips < 0: skips = 0 # Safety
            current_ins_line += "w " * skips
            obs_name = f"{sim_col}_R{run_no}"
            current_ins_line += f"!{obs_name}! "
            
            # Weight logic: 0 if missing (-99), else 1
            weight = 0.0 if val == -99 else 1.0
            
            obs_data.append({
                "obsnme": obs_name,
                "obsval": val if val != -99 else 0, # Use 0 as dummy value if missing
                "weight": weight,
                "obgnme": obs_col
            })
            last_idx = target_idx
            
        ins_lines.append(current_ins_line)

    with open(INS_FILE, 'w') as f:
        f.write("\n".join(ins_lines))
        
    # Create PST object
    par_data = []
    for p in params:
        par_data.append({
            "parnme": p['name'],
            "parval1": p['init'],
            "parlbnd": p['lower'],
            "parubnd": p['upper'],
            "pargp": "cultivar",
            "scale": 1.0,
            "offset": 0.0,
            "partrans": p['status']
        })
    
    par_df = pd.DataFrame(par_data)
    obs_df = pd.DataFrame(obs_data)
    
    if obs_df.empty:
        print("Warning: No valid observations found in Evaluate.OUT!")
        # Create a dummy observation to prevent crash?
        # PEST needs at least one observation.
        # But we can proceed, user needs to fix data.
    
    pst = pyemu.Pst.from_par_obs_names(par_df.parnme, obs_df.obsnme if not obs_df.empty else [])
    
    # Update parameter details
    par_df_indexed = par_df.set_index('parnme')
    for col in ['parval1', 'parlbnd', 'parubnd', 'pargp', 'partrans']:
        pst.parameter_data.loc[par_df.parnme, col] = par_df_indexed[col].values

    fixed_pars = par_df[par_df['parlbnd'] == par_df['parubnd']]['parnme']
    if not fixed_pars.empty:
        pst.parameter_data.loc[fixed_pars, 'partrans'] = 'fixed'
        
    # Only set zero-valued parameters to 'none' (linear) if they are NOT fixed
    zero_pars = par_df[(par_df['parval1'] == 0) & (par_df['parlbnd'] != par_df['parubnd'])]['parnme']
    if not zero_pars.empty:
         pst.parameter_data.loc[zero_pars, 'partrans'] = 'none'

    # Update observation details
    if not obs_df.empty:
        pst.observation_data.loc[obs_df.obsnme, 'obsval'] = obs_df.set_index('obsnme')['obsval']
        pst.observation_data.loc[obs_df.obsnme, 'obgnme'] = obs_df.set_index('obsnme')['obgnme']
        pst.observation_data.loc[obs_df.obsnme, 'weight'] = obs_df.set_index('obsnme')['weight']
    
    # Configure PEST++ IES (Iterative Ensemble Smoother)
    # -------------------------------------------------------------------------
    # Formal Run Recommendations:
    # noptmax: 3-5 iterations are usually sufficient for convergence.
    # ies_num_reals: 100-200 realizations provide publication-quality uncertainty statistics.
    # -------------------------------------------------------------------------
    pst.control_data.noptmax = 20           # Max iterations
    pst.pestpp_options["ies_num_reals"] = 100 # Increased to 100 for journal-quality statistics
    
    # Additional IES stability options
    pst.pestpp_options["ies_bad_phi_sigma"] = 2.0  # Drop realizations with very poor fit
    pst.pestpp_options["overdue_giveup_fac"] = 4.0 # Kill hung runs

    pst.model_command = ["python run_dssat.py"]
    # Key Change: Input is CSV TPL
    pst.model_input_data = pd.DataFrame({"pest_file": [PARAM_CSV_TPL], "model_file": [PARAM_CSV]})
    pst.model_output_data = pd.DataFrame({"pest_file": [INS_FILE], "model_file": [OUT_FILE]})
    
    pst.write(PST_FILE)
    print(f"PST file written to {PST_FILE}")

if __name__ == "__main__":
    params, lines, tm_idx = parse_cul_params()
    print(f"Found {len(params)} adjustable parameters.")
    create_param_csv_tpl(params)
    create_ins_and_pst(params)
