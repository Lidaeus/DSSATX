"""Generate evaluate_fixedsoil_{a3,official}_20260812.py from the a3 template."""
base = open('tools/calibration/evaluate_a3_20260810.py', encoding='utf-8').read()
variants = [
    ('a3', 'e02_v2_fixedsoil_joint_a3_25sp26sp_200x5_20260811', '189', 595.95,
     'windows/windows_a3_20260805/dscsm048_a3.exe', 'windows/windows_a3_20260805/Genotype/TMGRO048.SPE'),
    ('official', 'e02_v2_fixedsoil_joint_official_25sp26sp_200x5_20260811', '142', 590.90,
     'DSCSM048.EXE', r'C:\DSSAT48\Genotype\TMGRO048.SPE'),
]
for variant, case, member, phi, exe, spe in variants:
    s = base
    s = s.replace('a3-DSSAT joint calibration (20260810)', f'fixed-soil joint {variant} calibration (20260812)')
    s = s.replace(
        'Replays best member #117 of the a3-DSSAT joint calibration\n(e02_a3_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260810) on the\n25SP+26SP actual_trial bundles with the a3 exe (thresholded N uptake), then renders',
        f'Replays best member #{member} of the fixed-soil joint {variant} calibration\n({case}) on the 25SP+26SP actual_trial bundles (soil params FIXED), then renders')
    s = s.replace('python tools/calibration/evaluate_a3_20260810.py',
                  f'python tools/calibration/evaluate_fixedsoil_{variant}_20260812.py')
    s = s.replace('CASE = "e02_a3_joint_genetic_soiln_soilphys_25sp26sp_200x5_20260810"', f'CASE = "{case}"')
    s = s.replace('BEST_MEMBER = "117"  # min-Phi realization at final iteration (phi=591.66)',
                  f'BEST_MEMBER = "{member}"  # min-Phi realization at final iteration (phi={phi})')
    s = s.replace('EXE = ROOT / "windows/windows_a3_20260805/dscsm048_a3.exe"  # A3 thresholded N uptake',
                  f'EXE = ROOT / "{exe}"')
    s = s.replace('SPE = ROOT / "windows/windows_a3_20260805/Genotype/TMGRO048.SPE"  # a3 species file',
                  f'SPE = Path(r"{spe}")')
    s = s.replace('OUT_ROOT = FIGTURE / "a3_joint_soilphys_twoseason_20260810"',
                  f'OUT_ROOT = FIGTURE / "fixedsoil_{variant}_twoseason_20260812"')
    s = s.replace('DET_ROOT = RUN_DIR / f"best_member_{BEST_MEMBER}_deterministic_20260810"',
                  'DET_ROOT = RUN_DIR / f"best_member_{BEST_MEMBER}_deterministic_20260812"')
    s = s.replace('"design_id": f"{CASE}_best{BEST_MEMBER}_det_20260810",',
                  '"design_id": f"{CASE}_best{BEST_MEMBER}_det_20260812",')
    s = s.replace('bk_exe = ROOT / "workspace/DSCSM048.EXE.eval_a3"', f'bk_exe = ROOT / "workspace/DSCSM048.EXE.eval_fixedsoil_{variant}"')
    s = s.replace('bk_spe = GENOTYPE_DIR / "TMGRO048.SPE.base.eval_a3"', f'bk_spe = GENOTYPE_DIR / "TMGRO048.SPE.base.eval_fixedsoil_{variant}"')
    s = s.replace('pb = GENOTYPE_DIR / "TMGRO048.SPE.eval_a3"', f'pb = GENOTYPE_DIR / "TMGRO048.SPE.eval_fixedsoil_{variant}"')
    s = s.replace('"artifact_type": "two_season_diagnostics_a3_joint_soilphys_20260810",',
                  f'"artifact_type": "two_season_diagnostics_fixedsoil_{variant}_20260812",')
    s = s.replace('"dssat_version": "a3 build (windows/windows_a3_20260805/dscsm048_a3.exe)",',
                  f'"dssat_version": "{variant} fixed-soil build",')
    s = s.replace('"custom_genetic_params": "a3 set kept (NREXP/NRMIN/NUPK50/NUPCMN; NREXP/NRMIN inert in a3 build)",',
                  '"custom_genetic_params": "a3: kept; official: removed (NREXP/NRMIN/NUPK50/NUPCMN)",\n        "soil_params": "FIXED (user-approved values, not inverted)",')
    s = s.replace('print(f"a3-DSSAT joint calibration best member = #{BEST_MEMBER} (phi=591.66)")',
                  f'print(f"fixed-soil {variant} calibration best member = #{BEST_MEMBER} (phi={phi})")')
    s = s.replace('"--prefix", f"best{BEST_MEMBER}_det_a3",', '"--prefix", f"best{BEST_MEMBER}_det_' + variant + '",')
    open(f'tools/calibration/evaluate_fixedsoil_{variant}_20260812.py', 'w', encoding='utf-8').write(s)
    print('wrote evaluate_fixedsoil_' + variant + '_20260812.py')
