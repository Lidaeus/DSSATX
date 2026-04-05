"""run_parallel.py — 启动并行率定/SA 并管理运行状态。

阶段 3 重构：
- 新增 --status 子命令：查询各 agent 运行状态
- 补充 state/ 目录管理：PID 写入 state/agent.pid
- 运行结束后更新 run_status.json

用法：
    # 启动运行
    python tools/parallel/run_parallel.py \\
        --run-dir workspace/runs/my_run --case eggplant_stage2_v14

    # 查询状态
    python tools/parallel/run_parallel.py \\
        --run-dir workspace/runs/my_run --case eggplant_stage2_v14 --status
"""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone


def _repo_root_from_this_file():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", ".."))


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


def _ensure_case_pst(run_dir, case):
    pst = os.path.join(run_dir, f"{case}.pst")
    if not os.path.exists(pst):
        raise FileNotFoundError(pst)
    return pst


def _copy_dir(src_dir, dst_dir, ignore_names=None):
    ignore_names = set(ignore_names or [])

    def _ignore(_dir, names):
        return {n for n in names if n in ignore_names}

    if os.path.exists(dst_dir):
        shutil.rmtree(dst_dir, ignore_errors=True)
    shutil.copytree(src_dir, dst_dir, ignore=_ignore)


def _start_proc(exe, args, cwd, stdout_path, stderr_path):
    os.makedirs(cwd, exist_ok=True)
    out_f = open(stdout_path, "w", encoding="utf-8")
    err_f = open(stderr_path, "w", encoding="utf-8")
    try:
        p = subprocess.Popen(args, cwd=cwd, stdout=out_f, stderr=err_f, text=True)
    except Exception:
        out_f.close()
        err_f.close()
        raise
    return p, out_f, err_f


def _write_pid(path, pid):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="ascii") as f:
        f.write(str(int(pid)))


def _read_pid(path):
    """Read PID from file, return int or None."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="ascii") as f:
            return int(f.read().strip())
    except Exception:
        return None


def _is_pid_alive(pid):
    """Check if a process with given PID is running."""
    if pid is None:
        return False
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Get-Process -Id {pid} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0 and str(pid) in result.stdout
    except Exception:
        return False


def _stop_pidfile(pid_path):
    pid = _read_pid(pid_path)
    if pid is None:
        return
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue"],
            capture_output=True, text=True,
        )
    except Exception:
        pass


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _read_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _update_agent_last_job(agent_dir, **updates):
    """Update state/last_job.json for an agent."""
    state_dir = os.path.join(agent_dir, "state")
    path = os.path.join(state_dir, "last_job.json")
    data = _read_json(path) or {}
    data["last_updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data.update(updates)
    _write_json(path, data)


def _find_agent_pid(agent_dir):
    """Find agent PID from state/agent.pid or legacy panther_agent.pid."""
    pid = _read_pid(os.path.join(agent_dir, "state", "agent.pid"))
    if pid is None:
        pid = _read_pid(os.path.join(agent_dir, "panther_agent.pid"))
    return pid


def _find_manager_pid(run_dir):
    """Find manager PID from manager/ or legacy location."""
    pid = _read_pid(os.path.join(run_dir, "manager", "panther_manager.pid"))
    if pid is None:
        pid = _read_pid(os.path.join(run_dir, "panther_manager.pid"))
    return pid


# ═══════════════════════════════════════════════════════════════
# --status subcommand
# ═══════════════════════════════════════════════════════════════

def cmd_status(run_dir, agents_dir="_agents"):
    """Print status of all agents and manager."""
    agents_root = os.path.join(run_dir, agents_dir)

    print(f"\n{'='*60}")
    print(f"  Run Status: {run_dir}")
    print(f"{'='*60}")

    # Manager status
    mgr_pid = _find_manager_pid(run_dir)
    mgr_alive = _is_pid_alive(mgr_pid)
    mgr_status = "RUNNING" if mgr_alive else ("STOPPED" if mgr_pid else "NOT_STARTED")
    print(f"\n  Manager: {mgr_status} (PID: {mgr_pid or '-'})")

    # run_status.json
    run_status = _read_json(os.path.join(run_dir, "run_status.json"))
    if run_status:
        print(f"  Case:    {run_status.get('case', '?')}")
        print(f"  Mode:    {run_status.get('mode', '?')}")
        print(f"  Created: {run_status.get('created_at', '?')}")

    # Agent status
    if not os.path.isdir(agents_root):
        print(f"\n  No agents directory found: {agents_root}")
        return

    agent_dirs = sorted([
        d for d in os.listdir(agents_root)
        if os.path.isdir(os.path.join(agents_root, d)) and d.startswith("agent_")
    ])

    if not agent_dirs:
        print("\n  No agents found.")
        return

    print(f"\n  {'Agent':<12} {'PID':<8} {'Status':<12} {'Jobs':<6} {'Last Update'}")
    print(f"  {'-'*12} {'-'*8} {'-'*12} {'-'*6} {'-'*20}")

    running = 0
    stopped = 0
    not_started = 0

    for agent_name in agent_dirs:
        agent_dir = os.path.join(agents_root, agent_name)
        pid = _find_agent_pid(agent_dir)
        alive = _is_pid_alive(pid)

        if alive:
            status = "RUNNING"
            running += 1
        elif pid:
            status = "STOPPED"
            stopped += 1
        else:
            status = "NOT_STARTED"
            not_started += 1

        # Read last_job.json
        last_job = _read_json(os.path.join(agent_dir, "state", "last_job.json"))
        jobs = last_job.get("jobs_completed", "-") if last_job else "-"
        updated = last_job.get("last_updated_at", "-") if last_job else "-"
        if isinstance(updated, str) and len(updated) > 16:
            updated = updated[:16]

        pid_str = str(pid) if pid else "-"
        print(f"  {agent_name:<12} {pid_str:<8} {status:<12} {str(jobs):<6} {updated}")

    print(f"\n  Summary: {running} running, {stopped} stopped, {not_started} not started")
    print(f"{'='*60}\n")


# ═══════════════════════════════════════════════════════════════
# Run subcommand
# ═══════════════════════════════════════════════════════════════

def cmd_run(args):
    """Start parallel run."""
    run_dir = os.path.abspath(args.run_dir)
    if not os.path.isdir(run_dir):
        raise FileNotFoundError(run_dir)

    _ensure_case_pst(run_dir, args.case)

    n_agents = int(args.n_agents)
    if n_agents <= 0:
        cpu = os.cpu_count() or 1
        n_agents = max(1, int(cpu) - 2)

    port = int(args.port)
    if port <= 0:
        port = _choose_free_port()

    host = args.host or socket.gethostname()

    repo_root = _repo_root_from_this_file()
    exe_name = "pestpp-ies.exe" if args.mode == "ies" else "pestpp-sen.exe"
    exe_path = os.path.join(repo_root, "pestpp-5.2.16-win", "bin", exe_name)
    if not os.path.exists(exe_path):
        raise FileNotFoundError(exe_path)

    agents_root = os.path.join(run_dir, args.agents_dir)
    os.makedirs(agents_root, exist_ok=True)

    # Create manager/ dir
    manager_dir = os.path.join(run_dir, "manager")
    os.makedirs(manager_dir, exist_ok=True)

    ignore_names = {args.agents_dir, "_agents", "__pycache__", "manager", "state"}
    for i in range(1, int(n_agents) + 1):
        agent_dir = os.path.join(agents_root, f"agent_{i:02d}")
        _copy_dir(run_dir, agent_dir, ignore_names=ignore_names)
        # Create state/ directory
        state_dir = os.path.join(agent_dir, "state")
        os.makedirs(state_dir, exist_ok=True)
        _write_json(os.path.join(state_dir, "last_job.json"), {
            "agent_dir": f"agent_{i:02d}",
            "status": "idle",
            "last_updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "jobs_completed": 0,
            "last_exit_code": None,
        })

    print(f"mode={args.mode}")
    print(f"case={args.case}")
    print(f"run_dir={run_dir}")
    print(f"agents={n_agents}")
    print(f"host={host}")
    print(f"port={port}")
    print(f"exe={exe_path}")

    if args.dry_run:
        return

    agent_handles = []
    manager_handle = None
    stop_on_exit = True

    def _stop_all():
        # Stop manager
        for loc in [os.path.join(manager_dir, "panther_manager.pid"),
                     os.path.join(run_dir, "panther_manager.pid")]:
            _stop_pidfile(loc)
        # Stop agents
        for i in range(1, int(n_agents) + 1):
            agent_dir = os.path.join(agents_root, f"agent_{i:02d}")
            for loc in [os.path.join(agent_dir, "state", "agent.pid"),
                         os.path.join(agent_dir, "panther_agent.pid")]:
                _stop_pidfile(loc)

    try:
        for i in range(1, int(n_agents) + 1):
            agent_dir = os.path.join(agents_root, f"agent_{i:02d}")
            state_dir = os.path.join(agent_dir, "state")
            os.makedirs(state_dir, exist_ok=True)
            out_path = os.path.join(agent_dir, "panther_agent.stdout.log")
            err_path = os.path.join(agent_dir, "panther_agent.stderr.log")
            cmd = [exe_path, args.case, "/h", f"{host}:{port}"]
            p, out_f, err_f = _start_proc(exe_path, cmd, agent_dir, out_path, err_path)
            # Write PID to both locations
            _write_pid(os.path.join(state_dir, "agent.pid"), p.pid)
            _write_pid(os.path.join(agent_dir, "panther_agent.pid"), p.pid)
            _update_agent_last_job(agent_dir, status="running", pid=p.pid)
            agent_handles.append((p, out_f, err_f, agent_dir))

        time.sleep(0.4)

        manager_out = os.path.join(manager_dir, "panther_manager.stdout.log")
        manager_err = os.path.join(manager_dir, "panther_manager.stderr.log")
        manager_cmd = [exe_path, args.case, "/h", f":{port}"]
        p, out_f, err_f = _start_proc(exe_path, manager_cmd, run_dir, manager_out, manager_err)
        _write_pid(os.path.join(manager_dir, "panther_manager.pid"), p.pid)
        _write_pid(os.path.join(run_dir, "panther_manager.pid"), p.pid)
        manager_handle = (p, out_f, err_f)

        # Update run_status.json
        run_status_path = os.path.join(run_dir, "run_status.json")
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _write_json(run_status_path, {
            "run_dir": run_dir,
            "case": args.case,
            "mode": args.mode,
            "host": host,
            "port": port,
            "n_agents": n_agents,
            "started_at": now,
            "status": "running",
            "manager_pid": p.pid,
        })

        if args.wait:
            rc = p.wait()
            print(f"manager_exit_code={rc}")

            # Update run_status
            _write_json(run_status_path, {
                "run_dir": run_dir,
                "case": args.case,
                "mode": args.mode,
                "host": host,
                "port": port,
                "n_agents": n_agents,
                "started_at": now,
                "finished_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "status": "completed" if rc == 0 else f"failed (exit {rc})",
                "manager_pid": p.pid,
                "manager_exit_code": rc,
            })
        else:
            print("manager_started")
            stop_on_exit = False
            return

    except KeyboardInterrupt:
        _stop_all()
        raise
    finally:
        if stop_on_exit:
            try:
                _stop_all()
            except Exception:
                pass

        for p, out_f, err_f, agent_dir in agent_handles:
            try:
                _update_agent_last_job(agent_dir,
                                       status="stopped",
                                       last_exit_code=p.returncode)
            except Exception:
                pass
            try:
                out_f.close()
            except Exception:
                pass
            try:
                err_f.close()
            except Exception:
                pass

        if manager_handle is not None:
            p, out_f, err_f = manager_handle
            try:
                out_f.close()
            except Exception:
                pass
            try:
                err_f.close()
            except Exception:
                pass

        if args.cleanup:
            shutil.rmtree(agents_root, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(
        description="启动并行率定/SA 运行或查询运行状态"
    )
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--mode", choices=["ies", "sen"], default="ies")
    parser.add_argument("--n-agents", type=int, default=0)
    parser.add_argument("--agents-dir", default="_agents")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--wait", action="store_true", default=True)
    parser.add_argument("--no-wait", dest="wait", action="store_false")
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", action="store_true",
                        help="Query run status instead of starting a run")
    args = parser.parse_args()

    if args.status:
        cmd_status(os.path.abspath(args.run_dir), agents_dir=args.agents_dir)
        return

    if args.cleanup and not args.wait:
        raise ValueError("--cleanup requires --wait")

    cmd_run(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
