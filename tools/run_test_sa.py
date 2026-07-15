"""run_test_sa.py — 运行一次“迷你版”敏感性分析流程，专门用于测试架构联通性。
我们把采样率降到了最低（Morris r=4），以便在几分钟内跑完测试出全套流程。

用法：
    python tools/run_test_sa.py
"""

import os
import subprocess
import sys


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    root = _project_root()
    frozen_csv = os.path.join(root, "data", "parameter_registry", "bounds_frozen", "eggplant", "eggplant_v14_20260405.csv")
    case_dir = os.path.join(root, "workspace", "runs", "test_sa_workflow")
    
    # Python executable
    py = sys.executable

    print("\n[1/5] 创建迷你 Morris 敏感性分析 Case...")
    cmd = [
        py, os.path.join(root, "src", "sensitivity", "sa_build_sen_case.py"),
        "--param-review", frozen_csv,
        "--case-dir", case_dir,
        "--morris-r", "4"  # 极小采样，仅为跑通流程
    ]
    subprocess.run(cmd, check=True)

    print("\n[2/5] 准备 PANTHER 并行 Agent 沙箱 (mode=sen, n_agents=4)...")
    cmd = [
        py, os.path.join(root, "tools", "parallel", "prepare_agents.py"),
        "--run-dir", case_dir,
        "--case", "sa_sen_morris",
        "--mode", "sen",
        "--n-agents", "4"
    ]
    subprocess.run(cmd, check=True)

    print("\n[3/5] 启动 PANTHER 多进程并行评估 (这可能需要几分钟的时间)...")
    cmd = [
        py, os.path.join(root, "tools", "parallel", "run_parallel.py"),
        "--run-dir", case_dir,
        "--case", "sa_sen_morris",
        "--mode", "sen",
        "--n-agents", "4"
    ]
    subprocess.run(cmd, check=True)

    print("\n[4/5] 评估完成！开始后处理 Morris 结果报表...")
    cmd = [
        py, os.path.join(root, "src", "sensitivity", "sa_postprocess_morris.py"),
        "--case-dir", case_dir
    ]
    subprocess.run(cmd, check=True)

    print(f"\n[5/5] 🎉 联通性测试圆满成功！\n\n您可以进入 {os.path.relpath(case_dir, root)} \n查看 `morris_results.csv` 等结果文件。")


if __name__ == "__main__":
    main()
