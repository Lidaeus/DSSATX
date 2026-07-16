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

_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.common.run_state import classify_manager_exit


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
        deadline = time.time() + 5.0
        while os.path.exists(dst_dir) and time.time() < deadline:
            time.sleep(0.1)
            shutil.rmtree(dst_dir, ignore_errors=True)
        if os.path.exists(dst_dir):
            raise RuntimeError(f"agent_directory_in_use:{dst_dir}")
    shutil.copytree(src_dir, dst_dir, ignore=_ignore)


def _start_proc(exe, args, cwd, stdout_path, stderr_path, *, append=False, detached=False):
    os.makedirs(cwd, exist_ok=True)
    mode = "a" if append else "w"
    out_f = open(stdout_path, mode, encoding="utf-8")
    err_f = open(stderr_path, mode, encoding="utf-8")
    try:
        creationflags = 0
        if detached and os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        p = subprocess.Popen(
            args,
            cwd=cwd,
            stdout=out_f,
            stderr=err_f,
            text=True,
            creationflags=creationflags,
        )
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
    deadline = time.time() + 5.0
    while _is_pid_alive(pid) and time.time() < deadline:
        time.sleep(0.1)


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _read_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _update_run_status(run_dir, **updates):
    path = os.path.join(run_dir, "run_status.json")
    data = _read_json(path) or {}
    data.setdefault("state_schema_version", 2)
    data.update(updates)
    _write_json(path, data)
    return data


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
        print(f"  Process: {run_status.get('status', '?')}")
        print(f"  Science: {run_status.get('scientific_status', 'not_assessed')}")

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


def cmd_finalize(run_dir, case, mode="sen"):
    """Finalize a completed manager after its parent controller was lost.

    This path never resumes or re-runs the model. It requires terminal evidence
    for every design point, a final PEST++ summary, and a stopped manager.
    """
    run_dir = os.path.abspath(run_dir)
    if mode != "sen":
        raise ValueError("Offline finalization is currently supported only for sensitivity runs")
    manager_pid = _find_manager_pid(run_dir)
    if _is_pid_alive(manager_pid):
        raise RuntimeError(f"Refusing to finalize while manager is running: {manager_pid}")

    from src.common.quality import assess_morris, assess_morris_audit, load_morris_summary
    from src.sensitivity.morris_audit import audit_morris_case, write_morris_audit

    preliminary = audit_morris_case(run_dir, case=case)
    summary = preliminary["summary"]
    rec_path = os.path.join(run_dir, f"{case}.rec")
    rec_text = ""
    if os.path.isfile(rec_path):
        with open(rec_path, "r", encoding="utf-8", errors="ignore") as handle:
            rec_text = handle.read().lower()
    if int(summary.get("not_finalized_runs", 0)) != 0:
        raise RuntimeError("Refusing to finalize: design points remain non-terminal")
    if not bool(summary.get("mio_exists")):
        raise RuntimeError("Refusing to finalize: final Morris summary is missing")
    if "pestpp-sen analysis complete" not in rec_text:
        raise RuntimeError("Refusing to finalize: PEST++ completion marker is missing")
    if int(summary.get("runtime_failed_runs", 0)) or int(summary.get("unknown_failed_runs", 0)):
        raise RuntimeError("Refusing to finalize: runtime or unknown failures require recovery")

    current = _read_json(os.path.join(run_dir, "run_status.json")) or {}
    finished_at = _utc_now()
    _update_run_status(
        run_dir,
        status="completed",
        scientific_status="pending",
        finished_at=finished_at,
        manager_exit_code=0,
        termination_reason="offline_finalize_verified_complete",
        controller_recovered=True,
    )
    audit = audit_morris_case(run_dir, case=case)
    audit_dir = os.path.join(run_dir, "morris_audit")
    write_morris_audit(audit, audit_dir)
    run_quality = assess_morris_audit(audit, run_id=os.path.basename(run_dir))
    run_quality.write(audit_dir, stem="morris_run_quality")
    result_quality = assess_morris(
        load_morris_summary(os.path.join(run_dir, f"{case}.mio")),
        run_id=os.path.basename(run_dir),
    )
    result_quality.write(audit_dir, stem="morris_result_quality")
    scientific_status = (
        "validated"
        if run_quality.science_validated and result_quality.science_validated
        else "failed"
    )
    _update_run_status(
        run_dir,
        status="completed",
        scientific_status=scientific_status,
        scientific_status_error="",
        finished_at=finished_at,
        manager_exit_code=0,
        termination_reason="offline_finalize_verified_complete",
        controller_recovered=True,
        original_manager_pid=current.get("manager_pid"),
    )
    print(f"offline_finalize=completed scientific_status={scientific_status}")
    return scientific_status == "validated"


def cmd_stop(run_dir, agents_dir="_agents", *, force=False):
    """Request a traceable stop; force is reserved for unresponsive jobs."""
    run_dir = os.path.abspath(run_dir)
    manager_pid = _find_manager_pid(run_dir)
    if not _is_pid_alive(manager_pid):
        print("manager_not_running")
        return False

    now = _utc_now()
    if not force:
        stop_path = os.path.join(run_dir, "pest.stp")
        with open(stop_path, "w", encoding="ascii") as handle:
            handle.write("1\n")
        _update_run_status(
            run_dir,
            status="stopping",
            stop_requested_at=now,
            stop_mode="pest.stp",
            termination_reason="operator_graceful_stop_requested",
        )
        print(f"graceful_stop_requested={stop_path}")
        return True

    for path in [
        os.path.join(run_dir, "manager", "panther_manager.pid"),
        os.path.join(run_dir, "panther_manager.pid"),
    ]:
        _stop_pidfile(path)
    agents_root = os.path.join(run_dir, agents_dir)
    if os.path.isdir(agents_root):
        for name in os.listdir(agents_root):
            agent_dir = os.path.join(agents_root, name)
            if not os.path.isdir(agent_dir) or not name.startswith("agent_"):
                continue
            _stop_pidfile(os.path.join(agent_dir, "state", "agent.pid"))
            _stop_pidfile(os.path.join(agent_dir, "panther_agent.pid"))
    _update_run_status(
        run_dir,
        status="aborted",
        scientific_status="not_assessable",
        stop_requested_at=now,
        finished_at=now,
        stop_mode="force",
        termination_reason="operator_force_stop",
    )
    print("force_stop_completed")
    return True


def _launch_detached_controller(args):
    """Run the waiting controller outside the caller's console/process group."""
    run_dir = os.path.abspath(args.run_dir)
    _ensure_case_pst(run_dir, args.case)
    manager_dir = os.path.join(run_dir, "manager")
    os.makedirs(manager_dir, exist_ok=True)
    child_args = [value for value in sys.argv[1:] if value != "--no-wait"]
    child_args.extend(["--wait", "--detached-child"])
    stdout_path = os.path.join(manager_dir, "parallel_controller.stdout.log")
    stderr_path = os.path.join(manager_dir, "parallel_controller.stderr.log")
    process, out_f, err_f = _start_proc(
        sys.executable,
        [sys.executable, os.path.abspath(__file__), *child_args],
        _repo_root_from_this_file(),
        stdout_path,
        stderr_path,
        detached=True,
    )
    out_f.close()
    err_f.close()
    _update_run_status(
        run_dir,
        status="launching",
        scientific_status="pending",
        controller_pid=process.pid,
        controller_stdout=stdout_path,
        controller_stderr=stderr_path,
        launched_at=_utc_now(),
    )
    print(f"detached_controller_started={process.pid}")


# ═══════════════════════════════════════════════════════════════
# Run subcommand
# ═══════════════════════════════════════════════════════════════

def cmd_run(args):
    """Start parallel run."""
    run_dir = os.path.abspath(args.run_dir)
    if not os.path.isdir(run_dir):
        raise FileNotFoundError(run_dir)

    _ensure_case_pst(run_dir, args.case)
    if args.resume and not os.path.isfile(os.path.join(run_dir, f"{args.case}.rns")):
        raise FileNotFoundError(f"Cannot resume without run storage: {args.case}.rns")
    stop_file = os.path.join(run_dir, "pest.stp")
    if os.path.isfile(stop_file):
        os.remove(stop_file)

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

    ignore_names = {args.agents_dir, "_agents", "__pycache__", "manager", "state", "pest.stp"}
    ignore_names.update(
        name for name in os.listdir(run_dir)
        if os.path.splitext(name)[1].lower() in {".rns", ".rmr", ".rnu", ".rnj", ".rnf", ".mio"}
    )
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
            p, out_f, err_f = _start_proc(
                exe_path, cmd, agent_dir, out_path, err_path, append=args.resume
            )
            # Write PID to both locations
            _write_pid(os.path.join(state_dir, "agent.pid"), p.pid)
            _write_pid(os.path.join(agent_dir, "panther_agent.pid"), p.pid)
            _update_agent_last_job(agent_dir, status="running", pid=p.pid)
            agent_handles.append((p, out_f, err_f, agent_dir))

        time.sleep(0.4)

        manager_out = os.path.join(manager_dir, "panther_manager.stdout.log")
        manager_err = os.path.join(manager_dir, "panther_manager.stderr.log")
        manager_cmd = [exe_path, args.case]
        if args.resume:
            manager_cmd.append("/r")
        manager_cmd.extend(["/h", f":{port}"])
        p, out_f, err_f = _start_proc(
            exe_path, manager_cmd, run_dir, manager_out, manager_err, append=args.resume
        )
        _write_pid(os.path.join(manager_dir, "panther_manager.pid"), p.pid)
        _write_pid(os.path.join(run_dir, "panther_manager.pid"), p.pid)
        manager_handle = (p, out_f, err_f)

        # Update run_status.json
        run_status_path = os.path.join(run_dir, "run_status.json")
        now = _utc_now()
        previous = _read_json(run_status_path) or {}
        attempt = int(previous.get("attempt", 0) or 0) + 1
        _write_json(run_status_path, {
            "state_schema_version": 2,
            "run_dir": run_dir,
            "case": args.case,
            "mode": args.mode,
            "host": host,
            "port": port,
            "n_agents": n_agents,
            "started_at": now,
            "status": "running",
            "scientific_status": "pending",
            "manager_pid": p.pid,
            "attempt": attempt,
            "resumed": bool(args.resume),
        })

        if args.wait:
            rc = p.wait()
            print(f"manager_exit_code={rc}")

            current = _read_json(run_status_path) or {}
            stop_requested = bool(current.get("stop_requested_at"))
            process_state, termination_reason = classify_manager_exit(
                rc, stop_requested=stop_requested
            )
            scientific_status = "pending" if process_state == "completed" else "not_assessable"
            scientific_error = ""
            finished_at = _utc_now()
            # Persist process completion before the scientific audit reads
            # run_status.json. Scientific validity is a separate dimension.
            _write_json(run_status_path, {
                "state_schema_version": 2,
                "run_dir": run_dir,
                "case": args.case,
                "mode": args.mode,
                "host": host,
                "port": port,
                "n_agents": n_agents,
                "started_at": now,
                "finished_at": finished_at,
                "status": process_state,
                "scientific_status": scientific_status,
                "termination_reason": termination_reason,
                "manager_pid": p.pid,
                "manager_exit_code": rc,
                "attempt": attempt,
                "resumed": bool(args.resume),
            })
            if process_state == "completed" and args.mode == "sen":
                try:
                    from src.common.quality import (
                        assess_morris,
                        assess_morris_audit,
                        load_morris_summary,
                    )
                    from src.sensitivity.morris_audit import audit_morris_case, write_morris_audit

                    audit = audit_morris_case(run_dir, case=args.case)
                    audit_dir = os.path.join(run_dir, "morris_audit")
                    write_morris_audit(audit, audit_dir)
                    quality = assess_morris_audit(audit, run_id=os.path.basename(run_dir))
                    quality.write(audit_dir, stem="morris_run_quality")
                    result = load_morris_summary(
                        os.path.join(run_dir, f"{args.case}.mio")
                    )
                    result_quality = assess_morris(
                        result, run_id=os.path.basename(run_dir)
                    )
                    result_quality.write(audit_dir, stem="morris_result_quality")
                    scientific_status = (
                        "validated"
                        if quality.science_validated and result_quality.science_validated
                        else "failed"
                    )
                except Exception as exc:
                    scientific_status = "not_assessed"
                    scientific_error = str(exc)

            _write_json(run_status_path, {
                "state_schema_version": 2,
                "run_dir": run_dir,
                "case": args.case,
                "mode": args.mode,
                "host": host,
                "port": port,
                "n_agents": n_agents,
                "started_at": now,
                "finished_at": finished_at,
                "status": process_state,
                "scientific_status": scientific_status,
                "scientific_status_error": scientific_error,
                "termination_reason": termination_reason,
                "manager_pid": p.pid,
                "manager_exit_code": rc,
                "attempt": attempt,
                "resumed": bool(args.resume),
            })
        else:
            print("manager_started")
            stop_on_exit = False
            return

    except KeyboardInterrupt:
        _update_run_status(
            run_dir,
            status="aborted",
            scientific_status="not_assessable",
            finished_at=_utc_now(),
            termination_reason="keyboard_interrupt",
            manager_exit_code=0xC000013A,
        )
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
        description="Run, resume, stop, or inspect parallel PEST++ jobs"
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
    parser.add_argument("--finalize", action="store_true",
                        help="Finalize an already completed run after controller loss; never re-runs models")
    parser.add_argument("--stop", action="store_true",
                        help="Request a graceful, traceable stop using pest.stp")
    parser.add_argument("--force-stop", action="store_true",
                        help="Force-stop an unresponsive manager and agents")
    parser.add_argument("--resume", action="store_true",
                        help="Resume an interrupted run from the existing case.rns")
    parser.add_argument("--detached-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.status:
        cmd_status(os.path.abspath(args.run_dir), agents_dir=args.agents_dir)
        return
    if args.finalize:
        cmd_finalize(os.path.abspath(args.run_dir), args.case, mode=args.mode)
        return
    if args.stop or args.force_stop:
        cmd_stop(
            os.path.abspath(args.run_dir),
            agents_dir=args.agents_dir,
            force=bool(args.force_stop),
        )
        return

    if args.cleanup and not args.wait:
        raise ValueError("--cleanup requires --wait")

    if not args.wait and not args.detached_child:
        _launch_detached_controller(args)
        return

    try:
        cmd_run(args)
    except Exception as exc:
        _update_run_status(
            os.path.abspath(args.run_dir),
            status="runtime_failed",
            scientific_status="not_assessable",
            finished_at=_utc_now(),
            termination_reason="parallel_controller_exception",
            controller_error=str(exc),
        )
        raise


if __name__ == "__main__":
    sys.exit(main() or 0)
