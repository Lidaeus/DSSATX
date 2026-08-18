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
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.common.run_state import classify_manager_exit


def _repo_root_from_this_file():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", ".."))


# #region debug-point helper:runtime-report
def _debug_report(hypothesis_id, msg, *, data=None, run_id="pre-fix", location="tools/parallel/run_parallel.py"):
    try:
        env_path = os.path.join(_repo_root_from_this_file(), ".dbg", "pestpp-agent-disconnect.env")
        url = "http://127.0.0.1:7777/event"
        session_id = "pestpp-agent-disconnect"
        try:
            with open(env_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if line.startswith("DEBUG_SERVER_URL="):
                        url = line.split("=", 1)[1] or url
                    elif line.startswith("DEBUG_SESSION_ID="):
                        session_id = line.split("=", 1)[1] or session_id
        except Exception:
            pass
        payload = {
            "sessionId": session_id,
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "msg": msg,
            "data": data or {},
            "ts": int(time.time() * 1000),
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(request, timeout=1).read()
    except Exception:
        pass
# #endregion


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


def _wait_for_manager_start(process, *, timeout_s=10.0):
    """Give the PEST++ manager an exclusive startup window before agents connect.

    Starting agents first was racy on Windows: an early agent could repeatedly
    attempt the Panther security handshake before the manager had initialized,
    then exit while the manager waited forever for workers.  PEST++ does not
    expose a harmless readiness probe, so we instead require the manager to
    remain alive through a short initialization window.
    """
    deadline = time.monotonic() + float(timeout_s)
    while time.monotonic() < deadline:
        rc = process.poll()
        if rc is not None:
            raise RuntimeError(f"manager exited during startup (exit_code={rc})")
        time.sleep(0.1)
    return True


def _read_last_nonempty_line(path, *, max_bytes=4096):
    if not os.path.isfile(path):
        return ""
    with open(path, "rb") as handle:
        try:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - int(max_bytes)))
        except Exception:
            handle.seek(0)
        text = handle.read().decode("utf-8", errors="ignore")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _parse_manager_progress_line(line):
    match = re.search(
        r"runs\(C(?P<C>\d+)\s+\|F(?P<F>\d+)\s+\|T(?P<T>\d+)\s+\)\s+agents\(R(?P<R>\d+)\s+\|W(?P<W>\d+)\s+\|U(?P<U>\d+)\s+\)",
        line,
    )
    if not match:
        return None
    return {key: int(value) for key, value in match.groupdict().items()}


def _agent_disconnect_signature(agent_dir):
    line = _read_last_nonempty_line(os.path.join(agent_dir, "panther_agent.stdout.log"))
    return "receive from master failed" in line.lower(), line


def _wait_for_manager_with_agent_guard(manager_process, agent_handles, *, poll_s=0.5, manager_log_path=None, stall_timeout_s=180.0):
    """Wait for manager completion without silently orphaning a queued case."""
    stalled_signature = None
    stalled_since = None
    while True:
        rc = manager_process.poll()
        if rc is not None:
            _debug_report(
                "A",
                "[DEBUG] manager_exit_observed",
                data={"manager_pid": manager_process.pid, "manager_exit_code": rc},
                location="run_parallel.py:_wait_for_manager_with_agent_guard:manager_exit",
            )
            return rc
        if manager_log_path:
            progress_line = _read_last_nonempty_line(manager_log_path)
            progress = _parse_manager_progress_line(progress_line)
            if progress:
                disconnect_checks = [_agent_disconnect_signature(agent_dir) for *_, agent_dir in agent_handles]
                all_disconnected = bool(disconnect_checks) and all(flag for flag, _ in disconnect_checks)
                signature = (
                    progress["C"],
                    progress["F"],
                    progress["T"],
                    progress["R"],
                    progress["W"],
                    progress["U"],
                    all_disconnected,
                )
                stalled_pattern = (
                    progress["T"] > 0
                    and progress["W"] == 0
                    and progress["U"] == 0
                    and all_disconnected
                )
                if stalled_pattern:
                    if stalled_signature != signature:
                        stalled_signature = signature
                        stalled_since = time.monotonic()
                        _debug_report(
                            "B",
                            "[DEBUG] panther_stall_signature_detected",
                            data={
                                "manager_pid": manager_process.pid,
                                "progress": progress,
                                "manager_line": progress_line,
                                "agent_disconnect_lines": [line for _, line in disconnect_checks],
                            },
                            location="run_parallel.py:_wait_for_manager_with_agent_guard:stall_detected",
                        )
                    elif stalled_since is not None and (time.monotonic() - stalled_since) >= float(stall_timeout_s):
                        _debug_report(
                            "B",
                            "[DEBUG] panther_stall_timeout_abort",
                            data={
                                "manager_pid": manager_process.pid,
                                "stall_timeout_s": stall_timeout_s,
                                "progress": progress,
                                "manager_line": progress_line,
                                "agent_disconnect_lines": [line for _, line in disconnect_checks],
                            },
                            location="run_parallel.py:_wait_for_manager_with_agent_guard:stall_timeout",
                        )
                        raise RuntimeError(
                            "panther stall detected: manager remained active with pending timed-out tasks "
                            "while all agents reported receive-from-master failures"
                        )
                else:
                    stalled_signature = None
                    stalled_since = None
        if agent_handles and all(process.poll() is not None for process, *_ in agent_handles):
            exit_codes = [process.returncode for process, *_ in agent_handles]
            _debug_report(
                "A",
                "[DEBUG] all_agents_exited_while_manager_active",
                data={
                    "manager_pid": manager_process.pid,
                    "manager_alive": manager_process.poll() is None,
                    "agent_exit_codes": exit_codes,
                    "agent_pids": [process.pid for process, *_ in agent_handles],
                },
                location="run_parallel.py:_wait_for_manager_with_agent_guard:all_agents_exited",
            )
            raise RuntimeError(
                "all PEST++ agents exited while manager remained active "
                f"(agent_exit_codes={exit_codes})"
            )
        time.sleep(float(poll_s))


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


def _sensitivity_method(run_dir, case):
    """Return the configured PESTPP-SEN method without trusting the case name."""
    pst_path = os.path.join(run_dir, f"{case}.pst")
    if not os.path.isfile(pst_path):
        raise FileNotFoundError(pst_path)
    with open(pst_path, "r", encoding="utf-8", errors="ignore") as handle:
        text = handle.read().lower().replace(" ", "")
    return "sobol" if "++gsa_method(sobol)" in text else "morris"


def _assess_completed_sensitivity(run_dir, case):
    """Run the method-specific scientific audit after process completion."""
    method = _sensitivity_method(run_dir, case)
    if method == "sobol":
        from src.sensitivity.sobol_audit import write_sobol_audit

        report = write_sobol_audit(run_dir, case=case)
        return ("validated" if report.science_validated else "failed"), ""

    from src.common.quality import assess_morris, assess_morris_audit, load_morris_summary
    from src.sensitivity.morris_audit import audit_morris_case, write_morris_audit

    audit = audit_morris_case(run_dir, case=case)
    audit_dir = os.path.join(run_dir, "morris_audit")
    write_morris_audit(audit, audit_dir)
    quality = assess_morris_audit(audit, run_id=os.path.basename(run_dir))
    quality.write(audit_dir, stem="morris_run_quality")
    result = load_morris_summary(os.path.join(run_dir, f"{case}.mio"))
    result_quality = assess_morris(result, run_id=os.path.basename(run_dir))
    result_quality.write(audit_dir, stem="morris_result_quality")
    status = "validated" if quality.science_validated and result_quality.science_validated else "failed"
    return status, ""


def _assess_completed_ies(run_dir, case):
    """Run the IES engineering audit after process completion.

    The automatic audit records operational evidence only.  It must never
    promote ``scientific_status``; the dedicated finalize_calibration entry
    point performs the science gate after deterministic and validation review.
    """
    from src.calibration.engineering_gate import engineering_status, profile_for_run
    from src.reporting.quality_gate import assess_ies_run

    report = assess_ies_run(run_dir, case)
    audit_dir = os.path.join(run_dir, "ies_quality")
    os.makedirs(audit_dir, exist_ok=True)
    report.write(audit_dir, stem="ies_run_quality")
    profile = profile_for_run(run_dir, case)
    status, failures = engineering_status(report, profile)
    return status, ", ".join(failures)


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
        print(f"  Engineering: {run_status.get('engineering_status', 'not_assessed')}")
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
    if mode == "ies":
        from src.calibration.finalize_calibration import finalize_calibration
        manager_pid = _find_manager_pid(run_dir)
        if _is_pid_alive(manager_pid):
            raise RuntimeError(f"Refusing to finalize while manager is running: {manager_pid}")
        payload = finalize_calibration(run_dir, case)
        print(f"calibration_finalize={payload['science_status']}")
        return payload["science_status"] == "science_validated"
    if mode != "sen":
        raise ValueError("Offline finalization is currently supported only for sensitivity runs")
    manager_pid = _find_manager_pid(run_dir)
    if _is_pid_alive(manager_pid):
        raise RuntimeError(f"Refusing to finalize while manager is running: {manager_pid}")

    rec_path = os.path.join(run_dir, f"{case}.rec")
    rec_text = ""
    if os.path.isfile(rec_path):
        with open(rec_path, "r", encoding="utf-8", errors="ignore") as handle:
            rec_text = handle.read().lower()
    if "pestpp-sen analysis complete" not in rec_text:
        raise RuntimeError("Refusing to finalize: PEST++ completion marker is missing")
    method = _sensitivity_method(run_dir, case)
    if method == "morris":
        from src.sensitivity.morris_audit import audit_morris_case

        preliminary = audit_morris_case(run_dir, case=case)
        summary = preliminary["summary"]
        if int(summary.get("not_finalized_runs", 0)) != 0:
            raise RuntimeError("Refusing to finalize: design points remain non-terminal")
        if not bool(summary.get("mio_exists")):
            raise RuntimeError("Refusing to finalize: final Morris summary is missing")
        if int(summary.get("runtime_failed_runs", 0)) or int(summary.get("unknown_failed_runs", 0)):
            raise RuntimeError("Refusing to finalize: runtime or unknown failures require recovery")
    else:
        for suffix in ("sobol.par.csv", "sobol.obs.csv", "sobol.si.csv", "sobol.sti.csv"):
            if not os.path.isfile(os.path.join(run_dir, f"{case}.{suffix}")):
                raise RuntimeError(f"Refusing to finalize: final Sobol output is missing ({suffix})")

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
    scientific_status, scientific_error = _assess_completed_sensitivity(run_dir, case)
    _update_run_status(
        run_dir,
        status="completed",
        scientific_status=scientific_status,
        scientific_status_error=scientific_error,
        finished_at=finished_at,
        manager_exit_code=0,
        termination_reason="offline_finalize_verified_complete",
        controller_recovered=True,
        original_manager_pid=current.get("manager_pid"),
        prior_controller_error=current.get("controller_error", ""),
        controller_error="",
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
    if args.resume and args.mode == "ies":
        # pestpp-ies rejects the /r recourse option ('/r option not supported by
        # pestpp-ies'), so --resume cannot recover an interrupted IES run. Fail
        # fast with an actionable message before spawning agents. True IES
        # breakpoint recovery is deferred; rebuild from a clean case instead.
        raise NotImplementedError(
            "--resume is not supported with --mode ies: pestpp-ies rejects the "
            "/r recourse option. Rebuild from a clean case with build_pest.py "
            "and start a fresh run instead."
        )
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
        # Start the manager before workers.  Panther agents exchange a security
        # handshake on connection; launching them before the manager is ready
        # is a Windows race that can leave a live manager with zero workers.
        manager_out = os.path.join(manager_dir, "panther_manager.stdout.log")
        manager_err = os.path.join(manager_dir, "panther_manager.stderr.log")
        manager_cmd = [exe_path, args.case]
        if args.resume:
            manager_cmd.append("/r")
        manager_cmd.extend(["/h", f":{port}"])
        manager_process, out_f, err_f = _start_proc(
            exe_path, manager_cmd, run_dir, manager_out, manager_err, append=args.resume
        )
        _write_pid(os.path.join(manager_dir, "panther_manager.pid"), manager_process.pid)
        _write_pid(os.path.join(run_dir, "panther_manager.pid"), manager_process.pid)
        manager_handle = (manager_process, out_f, err_f)
        _debug_report(
            "C",
            "[DEBUG] manager_started",
            data={
                "case": args.case,
                "mode": args.mode,
                "port": port,
                "manager_pid": manager_process.pid,
                "resume": bool(args.resume),
            },
            location="run_parallel.py:cmd_run:manager_started",
        )

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
            "status": "starting_agents",
            "scientific_status": "pending",
            "engineering_status": "pending",
            "manager_pid": manager_process.pid,
            "attempt": attempt,
            "resumed": bool(args.resume),
        })
        _wait_for_manager_start(manager_process)

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
        _debug_report(
            "C",
            "[DEBUG] agents_started",
            data={
                "case": args.case,
                "port": port,
                "n_agents": n_agents,
                "agent_pids": [process.pid for process, *_ in agent_handles],
            },
            location="run_parallel.py:cmd_run:agents_started",
        )

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
            "engineering_status": "pending",
            "manager_pid": manager_process.pid,
            "attempt": attempt,
            "resumed": bool(args.resume),
        })

        if args.wait:
            try:
                rc = _wait_for_manager_with_agent_guard(
                    manager_process,
                    agent_handles,
                    manager_log_path=manager_out,
                )
            except RuntimeError as exc:
                _debug_report(
                    "D",
                    "[DEBUG] guard_runtime_error_before_stop_all",
                    data={
                        "error": str(exc),
                        "manager_pid": manager_process.pid,
                        "manager_alive_before_stop": _is_pid_alive(manager_process.pid),
                        "agent_states": [
                            {
                                "pid": process.pid,
                                "returncode": process.returncode,
                                "alive": process.poll() is None,
                            }
                            for process, *_ in agent_handles
                        ],
                    },
                    location="run_parallel.py:cmd_run:guard_exception_before_stop_all",
                )
                _update_run_status(
                    run_dir,
                    status="failed",
                    scientific_status="not_assessable",
                    engineering_status="engineering_failed",
                    engineering_status_error=str(exc),
                    finished_at=_utc_now(),
                    termination_reason="all_agents_disconnected",
                    manager_pid=manager_process.pid,
                )
                _stop_all()
                _debug_report(
                    "D",
                    "[DEBUG] guard_runtime_error_after_stop_all",
                    data={
                        "manager_pid": manager_process.pid,
                        "manager_alive_after_stop": _is_pid_alive(manager_process.pid),
                        "agent_states_after_stop": [
                            {
                                "pid": process.pid,
                                "returncode": process.returncode,
                                "alive": process.poll() is None,
                            }
                            for process, *_ in agent_handles
                        ],
                    },
                    location="run_parallel.py:cmd_run:guard_exception_after_stop_all",
                )
                raise
            print(f"manager_exit_code={rc}")
            p = manager_process

            current = _read_json(run_status_path) or {}
            stop_requested = bool(current.get("stop_requested_at"))
            process_state, termination_reason = classify_manager_exit(
                rc, stop_requested=stop_requested
            )
            scientific_status = "pending" if process_state == "completed" else "not_assessable"
            scientific_error = ""
            engineering_status = "pending" if process_state == "completed" else "not_assessable"
            engineering_error = ""
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
                "engineering_status": engineering_status,
                "termination_reason": termination_reason,
                "manager_pid": p.pid,
                "manager_exit_code": rc,
                "attempt": attempt,
                "resumed": bool(args.resume),
            })
            if process_state == "completed" and args.mode == "sen":
                try:
                    scientific_status, scientific_error = _assess_completed_sensitivity(
                        run_dir, args.case
                    )
                except Exception as exc:
                    scientific_status = "not_assessed"
                    scientific_error = str(exc)

            # P2-R0.6: formal IES completion auto-calls the quality assessment.
            # Writes ies_quality/ with per-round retention, Phi finiteness,
            # parameter update, and failure reasons. Failure blocks downstream.
            if process_state == "completed" and args.mode == "ies":
                try:
                    engineering_status, engineering_error = _assess_completed_ies(
                        run_dir, args.case
                    )
                    scientific_status = "not_assessed"
                    scientific_error = "Science gate deferred to finalize_calibration.py"
                except Exception as exc:
                    engineering_status = "engineering_not_assessed"
                    engineering_error = str(exc)
                    scientific_status = "not_assessed"
                    scientific_error = "Science gate deferred to finalize_calibration.py"

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
                "engineering_status": engineering_status,
                "engineering_status_error": engineering_error,
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
        _debug_report(
            "D",
            "[DEBUG] keyboard_interrupt_abort",
            data={"run_dir": run_dir, "case": args.case},
            location="run_parallel.py:cmd_run:keyboard_interrupt",
        )
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
        _debug_report(
            "D",
            "[DEBUG] outer_parallel_controller_exception",
            data={
                "run_dir": os.path.abspath(args.run_dir),
                "case": args.case,
                "mode": args.mode,
                "error": str(exc),
            },
            location="run_parallel.py:main:exception",
        )
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
