"""prepare_agents.py — 配置并行 agent 沙箱与启停脚本。

阶段 3 重构：
- 在每个 agent 目录下创建 state/ 子目录
- 生成 run_status.json 记录初始状态
- PID 文件写入 state/ 子目录（兼容旧位置）
- 在 run_dir 下生成 manager/ 子目录

用法：
    python tools/parallel/prepare_agents.py \\
        --run-dir workspace/runs/my_run \\
        --case eggplant_stage2_v14 \\
        [--n-agents 6] [--port 4010]
"""

import argparse
import json
import os
import shutil
import socket
from datetime import datetime, timezone


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


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _write_run_status(run_dir, case, n_agents, host, port, mode, agents_dir):
    """Generate run_status.json with initial state."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    status = {
        "run_dir": run_dir,
        "case": case,
        "mode": mode,
        "host": host,
        "port": port,
        "n_agents": n_agents,
        "agents_dir": agents_dir,
        "created_at": now,
        "status": "prepared",
        "manager": {
            "pid_file": "manager/panther_manager.pid",
            "stdout_log": "manager/panther_manager.stdout.log",
            "stderr_log": "manager/panther_manager.stderr.log",
            "status": "not_started",
        },
        "agents": [],
    }
    for i in range(1, n_agents + 1):
        agent_id = f"agent_{i:02d}"
        status["agents"].append({
            "id": agent_id,
            "pid_file": f"{agents_dir}/{agent_id}/state/agent.pid",
            "stdout_log": f"{agents_dir}/{agent_id}/panther_agent.stdout.log",
            "stderr_log": f"{agents_dir}/{agent_id}/panther_agent.stderr.log",
            "status": "not_started",
        })

    path = os.path.join(run_dir, "run_status.json")
    _write_json(path, status)
    return path


def _init_agent_state(agent_dir):
    """Create state/ subdirectory with initial files in agent sandbox."""
    state_dir = os.path.join(agent_dir, "state")
    os.makedirs(state_dir, exist_ok=True)

    # Initial last_job.json
    last_job = {
        "agent_dir": os.path.basename(agent_dir),
        "status": "idle",
        "last_updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "jobs_completed": 0,
        "last_exit_code": None,
    }
    _write_json(os.path.join(state_dir, "last_job.json"), last_job)
    return state_dir


def main():
    parser = argparse.ArgumentParser(
        description="准备并行 agent 沙箱目录与启停脚本"
    )
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--case", required=True,
                        help="PEST case name without extension")
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

    # ── Create manager/ subdirectory ──
    manager_dir = os.path.join(run_dir, "manager")
    os.makedirs(manager_dir, exist_ok=True)

    ignore_names = {args.agents_dir, "_agents", "__pycache__", "manager", "state"}

    # ── Create agent sandboxes ──
    for i in range(1, int(n_agents) + 1):
        agent_dir = os.path.join(agents_root, f"agent_{i:02d}")
        _copy_dir(run_dir, agent_dir, ignore_names=ignore_names)
        _init_agent_state(agent_dir)

    # ── Generate run_status.json ──
    status_path = _write_run_status(
        run_dir, args.case, n_agents, host, port, args.mode, args.agents_dir
    )

    # ── Generate PowerShell scripts ──
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.normpath(os.path.join(script_dir, "..", ".."))

    # Agent start (IES) — writes PID to state/agent.pid
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
  $stateDir = Join-Path $wd 'state'
  if (-not (Test-Path $stateDir)) {{ New-Item -ItemType Directory -Path $stateDir -Force | Out-Null }}
  $pidPath = Join-Path $stateDir 'agent.pid'
  $outPath = Join-Path $wd 'panther_agent.stdout.log'
  $errPath = Join-Path $wd 'panther_agent.stderr.log'
  $p = Start-Process -FilePath $IesExe -WorkingDirectory $wd -ArgumentList @($Case, '/h', "$HostName`:$Port") -PassThru -RedirectStandardOutput $outPath -RedirectStandardError $errPath -NoNewWindow:$NoNewWindow
  Set-Content -Path $pidPath -Value $p.Id -Encoding ascii
  # Also write to legacy location for backward compat
  Set-Content -Path (Join-Path $wd 'panther_agent.pid') -Value $p.Id -Encoding ascii
}}
"""

    # Manager start (IES) — writes PID to manager/panther_manager.pid
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
$mgr = Join-Path $CaseDir 'manager'
if (-not (Test-Path $mgr)) {{ New-Item -ItemType Directory -Path $mgr -Force | Out-Null }}
$pidPath = Join-Path $mgr 'panther_manager.pid'
$outPath = Join-Path $mgr 'panther_manager.stdout.log'
$errPath = Join-Path $mgr 'panther_manager.stderr.log'
$p = Start-Process -FilePath $IesExe -WorkingDirectory $CaseDir -ArgumentList @($Case, '/h', ":$Port") -PassThru -RedirectStandardOutput $outPath -RedirectStandardError $errPath -NoNewWindow:$NoNewWindow
Set-Content -Path $pidPath -Value $p.Id -Encoding ascii
# Legacy compat
Set-Content -Path (Join-Path $CaseDir 'panther_manager.pid') -Value $p.Id -Encoding ascii
if ($Wait) {{ Wait-Process -Id $p.Id }}
"""

    # SEN variants
    start_sen_agents = start_agents.replace("pestpp-ies.exe", "pestpp-sen.exe").replace("$IesExe", "$SenExe")
    start_sen_manager = start_manager.replace("pestpp-ies.exe", "pestpp-sen.exe").replace("$IesExe", "$SenExe")

    # Stop scripts
    stop_agents = f"""$ErrorActionPreference = 'Stop'
$CaseDir = Resolve-Path '{run_dir}'
$AgentsRoot = Join-Path $CaseDir '{args.agents_dir}'

Get-ChildItem -Path $AgentsRoot -Directory | Sort-Object Name | ForEach-Object {{
  $wd = $_.FullName
  # Try new location first, fallback to legacy
  $pidPath = Join-Path $wd 'state' 'agent.pid'
  if (-not (Test-Path $pidPath)) {{ $pidPath = Join-Path $wd 'panther_agent.pid' }}
  if (-not (Test-Path $pidPath)) {{ return }}
  $pid = Get-Content -Path $pidPath -ErrorAction SilentlyContinue
  if (-not $pid) {{ return }}
  try {{ Stop-Process -Id ([int]$pid) -Force -ErrorAction SilentlyContinue }} catch {{}}
}}
"""

    stop_manager = f"""$ErrorActionPreference = 'Stop'
$CaseDir = Resolve-Path '{run_dir}'
# Try new location first
$pidPath = Join-Path $CaseDir 'manager' 'panther_manager.pid'
if (-not (Test-Path $pidPath)) {{ $pidPath = Join-Path $CaseDir 'panther_manager.pid' }}
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
    print(f"  case:     {args.case}")
    print(f"  host:     {host}")
    print(f"  port:     {port}")
    print(f"  agents:   {n_agents}")
    print(f"  status:   {status_path}")
    print(f"  manager/: {manager_dir}")
    for i in range(1, min(4, n_agents + 1)):
        state_dir = os.path.join(agents_root, f"agent_{i:02d}", "state")
        print(f"  agent_{i:02d}/state/: {state_dir}")
    if n_agents > 3:
        print(f"  ... ({n_agents - 3} more agents)")


if __name__ == "__main__":
    main()
