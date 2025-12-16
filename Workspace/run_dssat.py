import os
import subprocess
import sys
import shutil
import time
import pandas as pd

# Configuration
DSSAT_EXE = "DSCSM048.EXE"
BATCH_FILE = "DSSBatch.v48"
CUL_BASE_FILE = "TMGRO048.CUL.base"
CUL_FILE = "TMGRO048.CUL"
PARAM_CSV = "pest_params.csv"

OUTPUT_FILES = [
    "PlantGro.OUT",
    "Evaluate.OUT",
    "Summary.OUT",
    "OVERVIEW.OUT",
    "WARNING.OUT"
]

def cleanup():
    """Remove existing output files to ensure fresh results."""
    for file in OUTPUT_FILES:
        if os.path.exists(file):
            try:
                os.remove(file)
            except Exception as e:
                print(f"Warning: Could not remove {file}: {e}")

def handle_failure(exit_code):
    """
    Handle model failure by creating a dummy Evaluate.OUT with high penalty.
    """
    print(f"DSSAT execution failed with exit code {exit_code}.")
    
    # Write a dummy Evaluate.OUT if it doesn't exist
    if not os.path.exists("Evaluate.OUT"):
        try:
            with open("Evaluate.OUT", "w") as f:
                f.write("*DSSAT Model Failed - Penalty Applied\n")
                f.write("@TRNO   RE     CR    T    T(D)    P    P(D)    L    L(D)    G    G(D)    M    M(D)    H    H(D)\n")
                # Write dummy line
                f.write("     1     1     1    -99    -99    -99    -99    -99    -99    -99    -99    -99    -99    -99    -99\n")
            print("Created dummy Evaluate.OUT")
        except Exception as e:
            print(f"Error creating dummy output: {e}")

def format_val(val):
    """Format value to fit in 6 characters for DSSAT CUL file."""
    # Handle exact zero
    if val == 0:
        return "  0.00"

    # Small numbers (e.g., WTPSD = 0.0040)
    if abs(val) < 0.1:
        s = f"{val:6.4f}"
        if len(s) <= 6: return s
        s = f"{val:6.3f}" # 0.004
        if len(s) <= 6: return s
        # Scientific notation for very small?
        # DSSAT might support .400E-2 (7 chars?)
        # Let's try stripping leading zero? .0040
        s = f"{val:.4f}".lstrip('0') 
        if len(s) <= 6: return f"{s:>6}"
    
    # Check if integer
    if val == int(val) and abs(val) < 100000:
        s = f"{int(val):6d}"
        if len(s) <= 6: return s
    
    # Float
    # If small (< 100), try 2 decimals
    if abs(val) < 100:
        s = f"{val:6.2f}"
        if len(s) <= 6: return s
        # If still too long (e.g. -10.00), try 1 decimal
        s = f"{val:6.1f}"
        if len(s) <= 6: return s
    
    # If large, try 1 decimal
    if abs(val) < 1000:
        s = f"{val:6.1f}"
        if len(s) <= 6: return s
    
    # If very small or large, use general format or stripped
    s = f"{val:6.3g}" # General format
    if len(s) <= 6: return s
    
    # Fallback: strict truncation?
    return f"{val:6.4g}"[:6]

def update_cul_file():
    """
    Reads pest_params.csv and TMGRO048.CUL.base, updates values, writes TMGRO048.CUL.
    """
    if not os.path.exists(PARAM_CSV):
        print(f"No {PARAM_CSV} found. Using base CUL file.")
        if os.path.exists(CUL_BASE_FILE):
            shutil.copy(CUL_BASE_FILE, CUL_FILE)
        return

    # Read Params
    try:
        # PEST CSV: name,value
        # But wait, TPL was: name,value
        # PEST writes strictly comma separated?
        # Let's check generated file format. Usually name,value with header if we put it.
        # But we used "ptf ~" and "name,value" in TPL.
        # PEST will replace the value.
        # So file will look like:
        # name,value
        # CSDL,12.33
        # ...
        
        # Read CSV
        params_df = pd.read_csv(PARAM_CSV)
        # Convert to dict
        param_dict = dict(zip(params_df['name'], params_df['value']))
        
    except Exception as e:
        print(f"Error reading parameter CSV: {e}")
        return

    if not os.path.exists(CUL_BASE_FILE):
        print(f"Error: {CUL_BASE_FILE} not found.")
        return

    with open(CUL_BASE_FILE, 'r') as f:
        lines = f.readlines()

    # Parse Base File to find column indices
    header_idx = -1
    tm0001_idx = -1
    
    for i, line in enumerate(lines):
        if line.startswith("@VAR#"):
            header_idx = i
        elif line.startswith("TM0001"):
            tm0001_idx = i

    if header_idx == -1 or tm0001_idx == -1:
        print("Error: Invalid CUL structure.")
        return

    # Map headers
    headers = lines[header_idx].split()
    # Headers: @VAR# VRNAME EXPNO ECO# CSDL ...
    # Indices: 0     1      2     3    4    ...
    # Parameter names start at index 4
    param_names = headers[4:]
    
    # Parse TM0001 line
    # TM0001 Florida 47 2010 Cal . TM0001 12.33 ...
    # We need to preserve the prefix.
    # Prefix: "TM0001 Florida 47 2010 Cal  . TM0001" (Length ~37?)
    # Let's verify content of base file line
    tm_line = lines[tm0001_idx]
    
    # We will reconstruct the values part.
    # But we need to handle the fixed width.
    # The prefix ends before the first value.
    # "TM0001" (val 1) starts after the dot and the second name?
    # No, the line is:
    # "TM0001 Florida... . TM0001 12.33 ..."
    # The columns correspond to CSDL, PPSEN...
    # CSDL is the first parameter.
    
    # Let's use split to get original values, then replace.
    parts = tm_line.split()
    # parts[0]=TM0001, [1]=Florida, [2]=47, [3]=2010, [4]=Cal, [5]=., [6]=TM0001, [7]=12.33
    # So values start at index 7.
    
    # Reconstruct line
    # We assume standard prefix width?
    # "TM0001 Florida 47 2010 Cal  . TM0001"
    # Let's just take the first 37 chars?
    # Or just use the first 7 parts joined?
    # But joining destroys spacing.
    
    # Better: Find the index of the start of the values.
    # We know the first value is 12.33 in the base file.
    val_start_pos = tm_line.find("12.33")
    if val_start_pos == -1:
        # Fallback
        prefix = "TM0001 Florida 47 2010 Cal  . TM0001"
    else:
        prefix = tm_line[:val_start_pos]
        
    # Construct new values string
    new_vals_str = ""
    
    # The order of param_names matches the values
    # We iterate through param_names and look up in param_dict
    
    # Get original values for fallback
    orig_vals = parts[7:]
    
    for i, name in enumerate(param_names):
        val = float(orig_vals[i]) # Default to original
        if name in param_dict:
            val = float(param_dict[name])
            
        # Format
        s_val = format_val(val)
        # Ensure it has leading space if needed?
        # DSSAT columns are usually space separated.
        # format_val returns 6 chars.
        # If we just append them, they will be packed.
        # "12.33 0.00" -> 6 chars each?
        # No, usually there is a space between columns or the column IS the width.
        # " 12.33  0.00"
        # If format_val returns 6 chars, it includes padding?
        # My format_val uses {:6s} which aligns right usually or we check.
        # f"{val:6.2f}" aligns right. " 12.33".
        # So concatenating them should work if the column width is exactly 6.
        
        new_vals_str += s_val
        
    # Combine
    new_line = prefix + new_vals_str + "\n"
    
    lines[tm0001_idx] = new_line
    
    with open(CUL_FILE, 'w') as f:
        f.writelines(lines)

def run_model():
    """Runs the DSSAT model."""
    print(f"Running {DSSAT_EXE} B {BATCH_FILE}...")
    
    try:
        # Set CWD to script directory
        cwd = os.path.dirname(os.path.abspath(__file__))
        
        start_time = time.time()
        
        # Run DSSAT
        # Note: DSCSM048.EXE requires the code (B) and batch file as arguments
        # It must be run in the directory containing the files
        result = subprocess.run(
            [DSSAT_EXE, "B", BATCH_FILE],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        end_time = time.time()
        print(f"Model run completed in {end_time - start_time:.2f} seconds.")
        
        if result.returncode != 0:
            handle_failure(result.returncode)
            print(f"Stdout: {result.stdout}")
            print(f"Stderr: {result.stderr}")
        else:
            # Verify output file exists and has content
            if not os.path.exists("Evaluate.OUT") or os.path.getsize("Evaluate.OUT") == 0:
                print("Evaluate.OUT missing or empty.")
                handle_failure(999)
            else:
                print("Evaluate.OUT generated successfully.")

    except Exception as e:
        print(f"Exception running model: {e}")
        handle_failure(998)

if __name__ == "__main__":
    cleanup()
    update_cul_file()
    run_model()
