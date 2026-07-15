import os, pathlib, re

path = r"d:\Tomato_Cal\src\calibration\build_pest.py"
text = pathlib.Path(path).read_text(encoding="utf-8")

# Replace WORKSPACE = r"..."
new_text = re.sub(
    r'^WORKSPACE\s*=\s*r"C:\\DSSAT48\\Tomato_Cal\\Workspace"', 
    r'WORKSPACE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "workspace")',
    text,
    flags=re.MULTILINE
)

# Redirect core files to read from data/templates and data/raw safely if not found
replacements = {
    'os.path.join(WORKSPACE, "SOIL.SOL")': 'os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "templates", "soil", "SOIL.SOL")',
    'os.path.join(WORKSPACE, "SOIL.SOL.base")': 'os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "templates", "soil", "SOIL.SOL.base")',
    'os.path.join(WORKSPACE, "TMGRO048.CUL.base")': 'os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "templates", "genotype", "TMGRO048.CUL.base")',
    'os.path.join(WORKSPACE, "TMGRO048.ECO")': 'os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "templates", "genotype", "TMGRO048.ECO")',
    'os.path.join(WORKSPACE, "TMGRO048.SPE")': 'os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "templates", "genotype", "TMGRO048.SPE")'
}

for old, new in replacements.items():
    new_text = new_text.replace(old, new)

if new_text != text:
    pathlib.Path(path).write_text(new_text, encoding="utf-8")
    print("Patched build_pest.py")
else:
    print("No changes needed in build_pest.py")
