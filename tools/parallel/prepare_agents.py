import argparse
import os
import shutil


def _copy_dir(src_dir, dst_dir, ignore_names=None):
    ignore_names = set(ignore_names or [])

    def _ignore(_dir, names):
        return {n for n in names if n in ignore_names}

    if os.path.exists(dst_dir):
        shutil.rmtree(dst_dir, ignore_errors=True)
    shutil.copytree(src_dir, dst_dir, ignore=_ignore)


def _write_ps1(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.replace("\r\n", "\n").replace("\n", "\r\n"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--case", required=True, help="PEST case name without extension, e.g., eggplant_stage2_v13")
    parser.add_argument("--n-agents", type=int, default=4)
    parser.add_argument("--agents-dir", default="_agents")
    parser.add_argument("--port", type=int, default=4010)
    args = parser.parse_args()

    run_dir = os.path.abspath(args.run_dir)
    agents_root = os.path.join(run_dir, args.agents_dir)
    os.makedirs(agents_root, exist_ok=True)

    ignore_names = {args.agents_dir, "_agents"}
    ignore_names.update({"__pycache__"})

    for i in range(1, int(args.n_agents) + 1):
        agent_dir = os.path.join(agents_root, f"agent_{i:02d}")
        _copy_dir(run_dir, agent_dir, ignore_names=ignore_names)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.normpath(os.path.join(script_dir, "..", ".."))
    ies_exe = os.path.join(repo_root, "pestpp-5.2.16-win", "bin", "pestpp-ies.exe")
    sen_exe = os.path.join(repo_root, "pestpp-5.2.16-win", "bin", "pestpp-sen.exe")

    start_agents = f"""$ErrorActionPreference = 'Stop'
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\\..')
$CaseDir = Resolve-Path '{run_dir}'
$AgentsRoot = Join-Path $CaseDir '{args.agents_dir}'
$Case = '{args.case}'
$Port = {int(args.port)}
$HostName = [System.Net.Dns]::GetHostName()
$IesExe = Join-Path $RepoRoot 'pestpp-5.2.16-win\\bin\\pestpp-ies.exe'

if (-not (Test-Path $IesExe)) {{ throw "pestpp-ies.exe not found: $IesExe" }}

Get-ChildItem -Path $AgentsRoot -Directory | Sort-Object Name | ForEach-Object {{
  $wd = $_.FullName
  Start-Process -FilePath $IesExe -WorkingDirectory $wd -ArgumentList @($Case, '/h', "$HostName`:$Port")
}}
"""

    start_manager = f"""$ErrorActionPreference = 'Stop'
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\\..')
$CaseDir = Resolve-Path '{run_dir}'
$Case = '{args.case}'
$Port = {int(args.port)}
$IesExe = Join-Path $RepoRoot 'pestpp-5.2.16-win\\bin\\pestpp-ies.exe'

if (-not (Test-Path $IesExe)) {{ throw "pestpp-ies.exe not found: $IesExe" }}
Start-Process -FilePath $IesExe -WorkingDirectory $CaseDir -ArgumentList @($Case, '/h', ":$Port") -Wait
"""

    start_sen_agents = f"""$ErrorActionPreference = 'Stop'
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\\..')
$CaseDir = Resolve-Path '{run_dir}'
$AgentsRoot = Join-Path $CaseDir '{args.agents_dir}'
$Case = '{args.case}'
$Port = {int(args.port)}
$HostName = [System.Net.Dns]::GetHostName()
$SenExe = Join-Path $RepoRoot 'pestpp-5.2.16-win\\bin\\pestpp-sen.exe'

if (-not (Test-Path $SenExe)) {{ throw "pestpp-sen.exe not found: $SenExe" }}

Get-ChildItem -Path $AgentsRoot -Directory | Sort-Object Name | ForEach-Object {{
  $wd = $_.FullName
  Start-Process -FilePath $SenExe -WorkingDirectory $wd -ArgumentList @($Case, '/h', "$HostName`:$Port")
}}
"""

    start_sen_manager = f"""$ErrorActionPreference = 'Stop'
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\\..')
$CaseDir = Resolve-Path '{run_dir}'
$Case = '{args.case}'
$Port = {int(args.port)}
$SenExe = Join-Path $RepoRoot 'pestpp-5.2.16-win\\bin\\pestpp-sen.exe'

if (-not (Test-Path $SenExe)) {{ throw "pestpp-sen.exe not found: $SenExe" }}
Start-Process -FilePath $SenExe -WorkingDirectory $CaseDir -ArgumentList @($Case, '/h', ":$Port") -Wait
"""

    _write_ps1(os.path.join(run_dir, "start_agents.ps1"), start_agents)
    _write_ps1(os.path.join(run_dir, "start_manager.ps1"), start_manager)
    _write_ps1(os.path.join(run_dir, "start_sen_agents.ps1"), start_sen_agents)
    _write_ps1(os.path.join(run_dir, "start_sen_manager.ps1"), start_sen_manager)

    print(f"Agents prepared: {agents_root}")
    print(f"Case: {args.case}")
    print(f"Port: {args.port}")
    print("Scripts written: start_agents.ps1, start_manager.ps1, start_sen_agents.ps1, start_sen_manager.ps1")


if __name__ == "__main__":
    main()

