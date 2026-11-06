$ErrorActionPreference = 'Stop'
$runDir = 'D:\Tomato_Cal\workspace\runs\e02_v2_rawdiff_terminal_nresp01_soil02_saactive_a3_nr_zp_200x4_20260806'
$case = 'e02_v2_rawdiff_terminal_nresp01_soil02_saactive_a3_nr_zp_200x4_20260806'
$env:PYTHONPATH = 'D:\Tomato_Cal'
$env:DSSAT_CUSTOM_EXE = 'D:\Tomato_Cal\windows\windows_a3_nr_zp_20260805\dscsm048_a3_nr_zp.exe'
$env:DSSAT_SPE_BASE = 'D:\Tomato_Cal\windows\windows_a3_nr_zp_20260805\Genotype\TMGRO048.SPE'
$env:DSSAT_SOIL_BASE = 'D:\Tomato_Cal\data\user\experiments\xxql2501_layermean_ic_valid_n012_v1_20260801\SOIL.SOL'
$env:DSSAT_KEEP_RUNS = '1'
Set-Location $runDir
python 'D:\Tomato_Cal\tools\parallel\run_parallel.py' --run-dir $runDir --case $case --mode ies --n-agents 4 --port 4071 --wait *> (Join-Path $runDir 'formal_console.log')
