"""package_release.py — 阶段 4：自动归档与发布包生成。

读取 run_dir 下的 run_manifest.yaml，将关键输出、快照配置以及最佳参数提取到一个 ZIP 文件中，
用于正式验收与发布。不包含无关的庞大中间输出（如各种 PST 演化记录）。

用法：
    python tools/package_release.py --run-dir workspace/runs/my_run --out-dir workspace/artifacts
"""

import argparse
import glob
import os
import re
from zipfile import ZipFile, ZIP_DEFLATED


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _parse_simple_yaml(path):
    """Parse a flat YAML without requiring pyyaml."""
    res = {}
    if not os.path.exists(path):
        return res
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.match(r"^([^:]+):\s*(.*)$", line)
            if match:
                k, v = match.groups()
                # strip simple quotes
                v = v.strip("'").strip('"')
                res[k.strip()] = v
    return res


def main():
    parser = argparse.ArgumentParser(description="生成校准发布包")
    parser.add_argument("--run-dir", required=True, help="率定任务运行目录")
    parser.add_argument("--out-dir", default=None, help="发布包保存目录（默认 workspace/artifacts）")
    args = parser.parse_args()

    run_dir = os.path.abspath(args.run_dir)
    manifest_path = os.path.join(run_dir, "run_manifest.yaml")
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"未找到 manifest 文件: {manifest_path}")

    manifest = _parse_simple_yaml(manifest_path)

    run_id = manifest.get("run_id", "unknown_run")
    timestamp = manifest.get("created_at", "").replace(":", "").replace("-", "")
    zip_name = f"{run_id}_{timestamp}.zip" if timestamp else f"{run_id}.zip"

    root = _project_root()
    out_dir = os.path.abspath(args.out_dir) if args.out_dir else os.path.join(root, "workspace", "artifacts")
    os.makedirs(out_dir, exist_ok=True)
    zip_path = os.path.join(out_dir, zip_name)

    print(f"[{run_id}] 正在打包发布文件 -> {zip_path}")

    files_to_pack = {}  # {arcname: abs_path}

    def _add(path, arc_path):
        if path and os.path.exists(path):
            files_to_pack[arc_path] = path

    # 1. Manifest itself
    _add(manifest_path, "run_manifest.yaml")

    # 2. Status
    _add(os.path.join(run_dir, "run_status.json"), "run_status.json")

    # 3. Parameters / bounds fast retrieval
    bounds_csv = manifest.get("bounds_csv")
    if bounds_csv:
        _add(bounds_csv, f"snapshots/bounds_{os.path.basename(bounds_csv)}")

    # 4. Result scripts and analysis
    # Best parameters
    for p in glob.glob(os.path.join(run_dir, "*best_parameters*.csv")):
        _add(p, f"results/{os.path.basename(p)}")
    
    # PST file
    pst_file = os.path.join(run_dir, f"{run_id}.pst")
    _add(pst_file, f"results/{run_id}.pst")

    # 5. Analysis outputs (CSV + PNG)
    # deterministic comparisons
    for p in glob.glob(os.path.join(run_dir, "*deterministic*compare*.csv")):
        _add(p, f"results/analysis/{os.path.basename(p)}")

    for p in glob.glob(os.path.join(run_dir, "plots", run_id, "*.png")):
        _add(p, f"results/plots/{os.path.basename(p)}")

    # 6. DSSAT Templates (Inputs)
    batch_file = manifest.get("batch_file")
    if batch_file:
        _add(os.path.join(run_dir, batch_file), f"snapshots/inputs/{os.path.basename(batch_file)}")
    
    # Typical DSSAT templates we want to freeze
    for ext in [".CUL", ".ECO", ".SPE", ".SOL"]:
        for p in glob.glob(os.path.join(run_dir, f"*{ext}")):
            _add(p, f"snapshots/inputs/{os.path.basename(p)}")
        for p in glob.glob(os.path.join(run_dir, f"*{ext}.base")):
            _add(p, f"snapshots/inputs/{os.path.basename(p)}")

    # Add weights
    _add(os.path.join(root, "configs", "runs", "tomato_cal.weights.csv"), "snapshots/inputs/tomato_cal.weights.csv")

    # Create ZIP
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as zf:
        for arcname, fpath in files_to_pack.items():
            zf.write(fpath, arcname)

    print(f"成功打包 {len(files_to_pack)} 个文件到发布包中。")
    print("\n包含以下模块：")
    for arcname in sorted(files_to_pack.keys()):
        print(f"  - {arcname}")


if __name__ == "__main__":
    main()
