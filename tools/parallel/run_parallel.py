import argparse
import os
import shutil
import socket
import subprocess
import sys
import time


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
    with open(path, "w", encoding="ascii") as f:
        f.write(str(int(pid)))


def _stop_pidfile(pid_path):
    if not os.path.exists(pid_path):
        return
    try:
        with open(pid_path, "r", encoding="ascii") as f:
            s = f.read().strip()
        pid = int(s)
    except Exception:
        return
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue",
            ],
            capture_output=True,
            text=True,
        )
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser()
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
    args = parser.parse_args()

    if args.cleanup and not args.wait:
        raise ValueError("--cleanup requires --wait")

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

    ignore_names = {args.agents_dir, "_agents", "__pycache__"}
    for i in range(1, int(n_agents) + 1):
        agent_dir = os.path.join(agents_root, f"agent_{i:02d}")
        _copy_dir(run_dir, agent_dir, ignore_names=ignore_names)

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
        if manager_handle is not None:
            _stop_pidfile(os.path.join(run_dir, "panther_manager.pid"))
        for i in range(1, int(n_agents) + 1):
            agent_dir = os.path.join(agents_root, f"agent_{i:02d}")
            _stop_pidfile(os.path.join(agent_dir, "panther_agent.pid"))

    try:
        for i in range(1, int(n_agents) + 1):
            agent_dir = os.path.join(agents_root, f"agent_{i:02d}")
            pid_path = os.path.join(agent_dir, "panther_agent.pid")
            out_path = os.path.join(agent_dir, "panther_agent.stdout.log")
            err_path = os.path.join(agent_dir, "panther_agent.stderr.log")
            cmd = [exe_path, args.case, "/h", f"{host}:{port}"]
            p, out_f, err_f = _start_proc(exe_path, cmd, agent_dir, out_path, err_path)
            _write_pid(pid_path, p.pid)
            agent_handles.append((p, out_f, err_f))

        time.sleep(0.4)

        manager_pid = os.path.join(run_dir, "panther_manager.pid")
        manager_out = os.path.join(run_dir, "panther_manager.stdout.log")
        manager_err = os.path.join(run_dir, "panther_manager.stderr.log")
        manager_cmd = [exe_path, args.case, "/h", f":{port}"]
        p, out_f, err_f = _start_proc(exe_path, manager_cmd, run_dir, manager_out, manager_err)
        _write_pid(manager_pid, p.pid)
        manager_handle = (p, out_f, err_f)

        if args.wait:
            rc = p.wait()
            print(f"manager_exit_code={rc}")
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

        for p, out_f, err_f in agent_handles:
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


if __name__ == "__main__":
    sys.exit(main() or 0)

