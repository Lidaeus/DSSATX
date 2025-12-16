import shutil
import os

DSSAT_ROOT = r"c:\DSSAT48"
WORKSPACE = r"c:\DSSAT48\Tomato_Cal\Workspace"
WEATHER_DIR = os.path.join(DSSAT_ROOT, "Weather")
SOIL_DIR = os.path.join(DSSAT_ROOT, "Soil")

# Ensure workspace exists
if not os.path.exists(WORKSPACE):
    os.makedirs(WORKSPACE)
    print(f"Created workspace directory: {WORKSPACE}")

# Weather files to copy
# Based on experiment files and available weather data
weather_files = [
    "UFBR9401.WTH", # For UFBR9401.TMX
    "UFGA0601.WTH", # For UFGA0602.TMX (Site UFGA, Year 06)
    "UFGA0701.WTH"  # For UFGA0701.TMX (Site UFGA, Year 07)
]

print("--- Copying Weather Files ---")
for wth in weather_files:
    src = os.path.join(WEATHER_DIR, wth)
    dst = os.path.join(WORKSPACE, wth)
    if os.path.exists(src):
        try:
            shutil.copy2(src, dst)
            print(f"Success: Copied {wth}")
        except Exception as e:
            print(f"Error copying {wth}: {e}")
    else:
        print(f"WARNING: Source file not found: {src}")

print("\n--- Copying Soil File ---")
soil_file = "SOIL.SOL"
src_soil = os.path.join(SOIL_DIR, soil_file)
dst_soil = os.path.join(WORKSPACE, soil_file)
if os.path.exists(src_soil):
    try:
        shutil.copy2(src_soil, dst_soil)
        print(f"Success: Copied {soil_file}")
    except Exception as e:
        print(f"Error copying {soil_file}: {e}")
else:
    print(f"WARNING: Source soil file not found: {src_soil}")

print("\n--- Copying Configuration Files ---")
# Copy DSSATPRO.v48 for path configuration
dssat_pro = "DSSATPRO.v48"
src_pro = os.path.join(DSSAT_ROOT, dssat_pro)
dst_pro = os.path.join(WORKSPACE, dssat_pro)

if os.path.exists(src_pro):
    try:
        shutil.copy2(src_pro, dst_pro)
        print(f"Success: Copied {dssat_pro}")
    except Exception as e:
        print(f"Error copying {dssat_pro}: {e}")
else:
    print(f"WARNING: {dssat_pro} not found in {DSSAT_ROOT}")

print("\nWorkspace setup update complete.")
