import os
import glob
import shutil
import argparse
import datetime


def _ensure_dir(p):
    os.makedirs(p, exist_ok=True)


def _unique_path(dst_path):
    if not os.path.exists(dst_path):
        return dst_path
    root, ext = os.path.splitext(dst_path)
    for i in range(1, 10000):
        cand = f"{root}.{i}{ext}"
        if not os.path.exists(cand):
            return cand
    return f"{root}.{datetime.datetime.now().strftime('%H%M%S%f')}{ext}"


def _move_files(file_paths, dst_dir):
    if not file_paths:
        return 0
    _ensure_dir(dst_dir)
    moved = 0
    for src in sorted(set(file_paths)):
        if not os.path.exists(src):
            continue
        dst = os.path.join(dst_dir, os.path.basename(src))
        dst = _unique_path(dst)
        try:
            shutil.move(src, dst)
            moved += 1
        except Exception:
            pass
    return moved


def _list_prefixes_from_pst(workspace):
    pst_files = glob.glob(os.path.join(workspace, "*.pst"))
    prefixes = []
    for p in pst_files:
        base = os.path.basename(p)
        if base.lower().endswith(".pst"):
            prefixes.append(base[:-4])
    return sorted(set(prefixes))


def _collect_artifacts_for_prefix(prefix):
    patterns = [
        f"{prefix}.rec",
        f"{prefix}.log",
        f"{prefix}.rei",
        f"{prefix}.rst",
        f"{prefix}.rns",
        f"{prefix}.par",
        f"{prefix}.sen",
        f"{prefix}.seo",
        f"{prefix}.mtt",
        f"{prefix}.jco",
        f"{prefix}.jac",
        f"{prefix}.msn",
        f"{prefix}.mio",
        f"{prefix}.mos",
        f"{prefix}.raw.csv",
        f"{prefix}.*.par.csv",
        f"{prefix}.*.obs.csv",
        f"{prefix}.*.pdc.csv",
        f"{prefix}.*.pcs.csv",
        f"{prefix}.*.rei",
        f"{prefix}.phi.*.csv",
        f"{prefix}.obs+noise.csv",
        f"{prefix}.weights.csv",
        f"{prefix}.adjusted.*.csv",
        f"{prefix}.rejected.*.csv",
        f"{prefix}.base.par",
        f"{prefix}.base.rei",
        f"{prefix}.*.base.par",
        f"{prefix}.*.base.rei",
        f"{prefix}pdc.csv",
        f"{prefix}pcs.csv",
    ]
    files = []
    for pat in patterns:
        files.extend(glob.glob(pat))
    return sorted(set(files))

def clean_workspace(prefix=None):
    workspace = os.getcwd()
    results_dir = os.path.join(workspace, "Calibration_Results")
    _ensure_dir(results_dir)

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_root = os.path.join(results_dir, "_runs", stamp)
    _ensure_dir(archive_root)

    prefixes = [prefix] if prefix else _list_prefixes_from_pst(workspace)

    moved_total = 0
    moved_prefixes = 0
    for pfx in prefixes:
        artifacts = _collect_artifacts_for_prefix(pfx)
        if artifacts:
            dst = os.path.join(archive_root, pfx)
            moved = _move_files(artifacts, dst)
            if moved > 0:
                moved_prefixes += 1
                moved_total += moved

    dssat_files = []
    for pat in ["*.OUT", "*.LST", "DSSAT48.LST", "LUN.*", "run.info"]:
        dssat_files.extend(glob.glob(pat))
    dssat_files = sorted(set(dssat_files))
    moved_total += _move_files(dssat_files, os.path.join(archive_root, "_dssat_io"))

    print(f"Archived {moved_total} files into: {archive_root}")
    if moved_prefixes == 0 and not dssat_files:
        print("No matching artifacts found in workspace.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--prefix", default=None)
    args = parser.parse_args()
    clean_workspace(prefix=args.prefix)
