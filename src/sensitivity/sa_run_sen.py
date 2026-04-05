import argparse
import os
import subprocess


def _repo_root_from_this_file():
    here = os.path.dirname(os.path.abspath(__file__))
    exe_rel = os.path.join("pestpp-5.2.16-win", "bin", "pestpp-sen.exe")
    for up in range(0, 8):
        cand = here
        for _ in range(up):
            cand = os.path.dirname(cand)
        if os.path.exists(os.path.join(cand, exe_rel)):
            return os.path.normpath(cand)
    return os.path.normpath(os.path.join(here, "..", "..", "..", ".."))


def _default_case_dir():
    workspace_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    return os.path.join(workspace_dir, "Sensitivity_Analyze", "SA_Project_Output", "sen_case")


def run_pestpp_sen(case_dir, pst_name, exe_path):
    pst_path = os.path.join(case_dir, pst_name)
    if not os.path.exists(pst_path):
        raise FileNotFoundError(pst_path)
    if not os.path.exists(exe_path):
        raise FileNotFoundError(exe_path)

    proc = subprocess.run([exe_path, pst_name], cwd=case_dir, capture_output=True, text=True)
    log_path = os.path.join(case_dir, pst_name + ".log.txt")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(proc.stdout or "")
        f.write("\n")
        f.write(proc.stderr or "")

    if proc.returncode != 0:
        raise RuntimeError(f"pestpp-sen failed ({proc.returncode}). See: {log_path}")
    return log_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", default=None)
    parser.add_argument("--mode", choices=["morris", "sobol"], default="morris")
    args = parser.parse_args()

    repo_root = _repo_root_from_this_file()
    exe_path = os.path.join(repo_root, "pestpp-5.2.16-win", "bin", "pestpp-sen.exe")
    case_dir = os.path.normpath(args.case_dir) if args.case_dir else _default_case_dir()

    pst_name = "sa_sen_morris.pst" if args.mode == "morris" else "sa_sen_sobol.pst"
    log_path = run_pestpp_sen(case_dir=case_dir, pst_name=pst_name, exe_path=exe_path)
    print(f"OK: {log_path}")


if __name__ == "__main__":
    main()
