import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path('D:/Tomato_Cal')
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.calibration.evaluate_fixedsoil_official_best189_20260813 as evaluation

RUN_DIR = ROOT / 'workspace/runs/e02_formal_v46_dias2026_champion_nitrogen_20260831'
DET_ROOT = RUN_DIR
OUT_ROOT = ROOT / 'figture/e02_formal_v46_dias2026_champion_nitrogen_20260831'

evaluation.RUN_DIR = RUN_DIR
evaluation.DET_ROOT = DET_ROOT
evaluation.OUT_ROOT = OUT_ROOT
evaluation.FIGTURE = ROOT / 'figture'
evaluation.CASE = 'e02_formal_v46_dias2026_champion_nitrogen_20260831'
evaluation.BEST_MEMBER = 'dias_champion'
evaluation.SOURCE_ITERATION = 1
evaluation.BEST_PHI = 582.4
evaluation.CALIBRATION_STATE = 'completed_dias2026_nitrogen_optimized'
evaluation.ARTIFACT_TYPE = 'formal_deterministic_e02_formal_v46_dias2026_champion_nitrogen_20260831'
evaluation.SPE = ROOT / 'data/templates/genotype/TMGRO048.SPE.base'
evaluation.HARVEST_OBJECTIVE = 'increment_plus_terminal + HARVEST_DRY_TREND (log)'
evaluation.SOIL_INJECTION_DESCRIPTION = 'enabled (calibrated SBDM/SLPF/SSKS/SLCL/SLSI applied; SLPF fixed 0.93)'
evaluation.DSSAT_VERSION_DESCRIPTION = 'official fixed-soil build with Dias et al. 2026 species-N parameterization'
evaluation.SOIL_PARAMETER_STATUS = 'FIXED (user-approved values, not inverted)'
evaluation.BUNDLE_NOTE = 'actual_trial bundles: xxql2501_formal_scheme4_soil_20260830 / xxql2601_formal_scheme4_soil_20260830'
evaluation.SEASONS = [
    {'season_id': '25SP', 'excode': 'XXQL2501',
     'treatments': [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
     'bundle': ROOT / 'data/user/experiments/xxql2501_formal_scheme4_soil_20260830'},
    {'season_id': '26SP', 'excode': 'XXQL2601',
     'treatments': list(range(1, 13)),
     'bundle': ROOT / 'data/user/experiments/xxql2601_formal_scheme4_soil_20260830'},
]

OUT_ROOT.mkdir(parents=True, exist_ok=True)
evaluation.main()
print(f'Generated diagnostic suite in {OUT_ROOT}')
