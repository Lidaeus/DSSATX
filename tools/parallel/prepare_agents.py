import argparse
import os
import shutil
import socket


def _choose_free_port(start=4010, end=4999):
    for port in range(int(start), int(end) + 1):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
            return port
        except OSError:
            continue
        finally:
            try:
                s.close()
            except Exception:
                pass
    raise RuntimeError("no_free_port")


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
    parser.add_argument("--mode", choices=["ies", "sen", "both"], default="both")
    parser.add_argument("--n-agents", type=int, default=0)
    parser.add_argument("--agents-dir", default="_agents")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--host", default=None)
    args = parser.parse_args()

    run_dir = os.path.abspath(args.run_dir)
    if not os.path.isdir(run_dir):
        raise FileNotFoundError(run_dir)
    pst_path = os.path.join(run_dir, f"{args.case}.pst")
    if not os.path.exists(pst_path):
        raise FileNotFoundError(pst_path)

    n_agents = int(args.n_agents)
    if n_agents <= 0:
        cpu = os.cpu_count() or 1
        n_agents = max(1, int(cpu) - 2)

    port = int(args.port)
    if port <= 0:
        port = _choose_free_port()

    host = args.host or socket.gethostname()

    agents_root = os.path.join(run_dir, args.agents_dir)
    os.makedirs(agents_root, exist_ok=True)

    ignore_names = {args.agents_dir, "_agents"}
    ignore_names.update({"__pycache__"})

    for i in range(1, int(n_agents) + 1):
        agent_dir = os.path.join(agents_root, f"agent_{i:02d}")
        _copy_dir(run_dir, agent_dir, ignore_names=ignore_names)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.normpath(os.path.join(script_dir, "..", ".."))
    ies_exe = os.path.join(repo_root, "pestpp-5.2.16-win", "bin", "pestpp-ies.exe")
    sen_exe = os.path.join(repo_root, "pestpp-5.2.16-win", "bin", "pestpp-sen.exe")

    start_agents = f"""param(
  [switch]$NoNewWindow
)
$ErrorActionPreference = 'Stop'
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\\..')
$CaseDir = Resolve-Path '{run_dir}'
$AgentsRoot = Join-Path $CaseDir '{args.agents_dir}'
$Case = '{args.case}'
$Port = {int(port)}
$HostName = '{host}'
$IesExe = Join-Path $RepoRoot 'pestpp-5.2.16-win\\bin\\pestpp-ies.exe'

if (-not (Test-Path $IesExe)) {{ throw "pestpp-ies.exe not found: $IesExe" }}

Get-ChildItem -Path $AgentsRoot -Directory | Sort-Object Name | ForEach-Object {{
  $wd = $_.FullName
  $pidPath = Join-Path $wd 'panther_agent.pid'
  $outPath = Join-Path $wd 'panther_agent.stdout.log'
  $errPath = Join-Path $wd 'panther_agent.stderr.log'
  $p = Start-Process -FilePath $IesExe -WorkingDirectory $wd -ArgumentList @($Case, '/h', "$HostName`:$Port") -PassThru -RedirectStandardOutput $outPath -RedirectStandardError $errPath -NoNewWindow:$NoNewWindow
  Set-Content -Path $pidPath -Value $p.Id -Encoding ascii
}}
"""

    start_manager = f"""param(
  [switch]$Wait = $true,
  [switch]$NoNewWindow
)
$ErrorActionPreference = 'Stop'
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\\..')
$CaseDir = Resolve-Path '{run_dir}'
$Case = '{args.case}'
$Port = {int(port)}
$IesExe = Join-Path $RepoRoot 'pestpp-5.2.16-win\\bin\\pestpp-ies.exe'

if (-not (Test-Path $IesExe)) {{ throw "pestpp-ies.exe not found: $IesExe" }}
$pidPath = Join-Path $CaseDir 'panther_manager.pid'
$outPath = Join-Path $CaseDir 'panther_manager.stdout.log'
$errPath = Join-Path $CaseDir 'panther_manager.stderr.log'
$p = Start-Process -FilePath $IesExe -WorkingDirectory $CaseDir -ArgumentList @($Case, '/h', ":$Port") -PassThru -RedirectStandardOutput $outPath -RedirectStandardError $errPath -NoNewWindow:$NoNewWindow
Set-Content -Path $pidPath -Value $p.Id -Encoding ascii
if ($Wait) {{ Wait-Process -Id $p.Id }}
"""

    start_sen_agents = f"""param(
  [switch]$NoNewWindow
)
$ErrorActionPreference = 'Stop'
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\\..')
$CaseDir = Resolve-Path '{run_dir}'
$AgentsRoot = Join-Path $CaseDir '{args.agents_dir}'
$Case = '{args.case}'
$Port = {int(port)}
$HostName = '{host}'
$SenExe = Join-Path $RepoRoot 'pestpp-5.2.16-win\\bin\\pestpp-sen.exe'

if (-not (Test-Path $SenExe)) {{ throw "pestpp-sen.exe not found: $SenExe" }}

Get-ChildItem -Path $AgentsRoot -Directory | Sort-Object Name | ForEach-Object {{
  $wd = $_.FullName
  $pidPath = Join-Path $wd 'panther_agent.pid'
  $outPath = Join-Path $wd 'panther_agent.stdout.log'
  $errPath = Join-Path $wd 'panther_agent.stderr.log'
  $p = Start-Process -FilePath $SenExe -WorkingDirectory $wd -ArgumentList @($Case, '/h', "$HostName`:$Port") -PassThru -RedirectStandardOutput $outPath -RedirectStandardError $errPath -NoNewWindow:$NoNewWindow
  Set-Content -Path $pidPath -Value $p.Id -Encoding ascii
}}
"""

    start_sen_manager = f"""param(
  [switch]$Wait = $true,
  [switch]$NoNewWindow
)
$ErrorActionPreference = 'Stop'
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\\..')
$CaseDir = Resolve-Path '{run_dir}'
$Case = '{args.case}'
$Port = {int(port)}
$SenExe = Join-Path $RepoRoot 'pestpp-5.2.16-win\\bin\\pestpp-sen.exe'

if (-not (Test-Path $SenExe)) {{ throw "pestpp-sen.exe not found: $SenExe" }}
$pidPath = Join-Path $CaseDir 'panther_manager.pid'
$outPath = Join-Path $CaseDir 'panther_manager.stdout.log'
$errPath = Join-Path $CaseDir 'panther_manager.stderr.log'
$p = Start-Process -FilePath $SenExe -WorkingDirectory $CaseDir -ArgumentList @($Case, '/h', ":$Port") -PassThru -RedirectStandardOutput $outPath -RedirectStandardError $errPath -NoNewWindow:$NoNewWindow
Set-Content -Path $pidPath -Value $p.Id -Encoding ascii
if ($Wait) {{ Wait-Process -Id $p.Id }}
"""

    stop_agents = f"""$ErrorActionPreference = 'Stop'
$CaseDir = Resolve-Path '{run_dir}'
$AgentsRoot = Join-Path $CaseDir '{args.agents_dir}'

Get-ChildItem -Path $AgentsRoot -Directory | Sort-Object Name | ForEach-Object {{
  $wd = $_.FullName
  $pidPath = Join-Path $wd 'panther_agent.pid'
  if (-not (Test-Path $pidPath)) {{ return }}
  $pid = Get-Content -Path $pidPath -ErrorAction SilentlyContinue
  if (-not $pid) {{ return }}
  try {{ Stop-Process -Id ([int]$pid) -Force -ErrorAction SilentlyContinue }} catch {{}}
}}
"""

    stop_manager = f"""$ErrorActionPreference = 'Stop'
$CaseDir = Resolve-Path '{run_dir}'
$pidPath = Join-Path $CaseDir 'panther_manager.pid'
if (-not (Test-Path $pidPath)) {{ exit 0 }}
$pid = Get-Content -Path $pidPath -ErrorAction SilentlyContinue
if (-not $pid) {{ exit 0 }}
try {{ Stop-Process -Id ([int]$pid) -Force -ErrorAction SilentlyContinue }} catch {{}}
"""

    clean_agents = f"""$ErrorActionPreference = 'Stop'
$CaseDir = Resolve-Path '{run_dir}'
$AgentsRoot = Join-Path $CaseDir '{args.agents_dir}'
if (Test-Path $AgentsRoot) {{ Remove-Item -Recurse -Force $AgentsRoot }}
"""

    if args.mode in {"ies", "both"}:
        _write_ps1(os.path.join(run_dir, "start_agents.ps1"), start_agents)
        _write_ps1(os.path.join(run_dir, "start_manager.ps1"), start_manager)
        _write_ps1(os.path.join(run_dir, "stop_agents.ps1"), stop_agents)
        _write_ps1(os.path.join(run_dir, "stop_manager.ps1"), stop_manager)
        _write_ps1(os.path.join(run_dir, "clean_agents.ps1"), clean_agents)

    if args.mode in {"sen", "both"}:
        _write_ps1(os.path.join(run_dir, "start_sen_agents.ps1"), start_sen_agents)
        _write_ps1(os.path.join(run_dir, "start_sen_manager.ps1"), start_sen_manager)
        _write_ps1(os.path.join(run_dir, "stop_sen_agents.ps1"), stop_agents)
        _write_ps1(os.path.join(run_dir, "stop_sen_manager.ps1"), stop_manager)
        _write_ps1(os.path.join(run_dir, "clean_sen_agents.ps1"), clean_agents)

    print(f"Agents prepared: {agents_root}")
    print(f"Case: {args.case}")
    print(f"Host: {host}")
    print(f"Port: {port}")
    print(f"Agents: {n_agents}")
    print("Scripts written under run_dir")


if __name__ == "__main__":
    main()
