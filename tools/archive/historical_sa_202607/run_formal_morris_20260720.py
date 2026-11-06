"""T4 三季正式 Morris 敏感性分析 —— 一键运行脚本.

用法:
  # 运行所有 9 个案例 (按季节依次执行)
  python tools/sa/run_formal_morris_20260720.py --run-all

  # 只运行某个季节
  python tools/sa/run_formal_morris_20260720.py --season XXQL2501

  # 检查当前状态
  python tools/sa/run_formal_morris_20260720.py --status

  # 验证失败率 + 后处理 (在全部运行完成后)
  python tools/sa/run_formal_morris_20260720.py --postprocess
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CASE_ROOT = PROJECT_ROOT / "workspace" / "runs" / "formal_morris"

SEASONS = {
    "XXQL2501": {
        "contract": "configs/sa/eggplant_formal_xxql2501_outputs_20260720.json",
        "bundle": "data/user/experiments/xxql2501_sa_controlled_candidate_20260720",
    },
    "XXQL2502": {
        "contract": "configs/sa/eggplant_formal_xxql2502_outputs_20260720.json",
        "bundle": "data/user/experiments/xxql2502_sa_controlled_candidate_20260720",
    },
    "XXQL2601": {
        "contract": "configs/sa/eggplant_formal_xxql2601_outputs_20260720.json",
        "bundle": "data/user/experiments/xxql2601_sa_controlled_tn12_w1_candidate_20260721",
    },
}

SEEDS = [20260729, 20260812, 20260826]
N_AGENTS = 3  # agents per case


def _case_dir(season: str, seed: int) -> Path:
    return CASE_ROOT / season / f"seed_{seed}"


def _case_rec(season: str, seed: int) -> Path:
    return _case_dir(season, seed) / "sa_sen_morris.rec"


def _is_complete(season: str, seed: int) -> bool:
    rec = _case_rec(season, seed)
    if rec.exists():
        return "analysis complete" in rec.read_text(encoding="utf-8", errors="ignore")
    return False


def _run_manager_log(season: str, seed: int) -> Path | None:
    log = _case_dir(season, seed) / "manager" / "panther_manager.stdout.log"
    return log if log.exists() else None


def _completed_failed(season: str, seed: int) -> tuple[int, int]:
    log = _run_manager_log(season, seed)
    if not log:
        return 0, 0
    text = log.read_text(encoding="utf-8", errors="ignore")
    c_vals = re.findall(r"C(\d+)", text)
    f_vals = re.findall(r"F(\d+)", text)
    return int(c_vals[-1]) if c_vals else 0, int(f_vals[-1]) if f_vals else 0


def cmd_status():
    """Print status of all 9 cases."""
    print("=" * 60)
    print("T4 Morris 案例状态")
    print("=" * 60)
    for season in SEASONS:
        print(f"\n--- {season} ---")
        for seed in SEEDS:
            c, f = _completed_failed(season, seed)
            if _is_complete(season, seed):
                status = "COMPLETE"
            elif _run_manager_log(season, seed):
                status = "RUNNING"
            else:
                status = "NOT STARTED"
            print(f"  seed_{seed}: {status:12s}  (completed={c:>4d}, failed={f:>3d})")


def cmd_run_season(season: str):
    """Launch all 3 seeds for one season, wait for completion."""
    print(f"\n{'=' * 60}")
    print(f"启动 {season} 三 seed Morris (每 case {N_AGENTS} agents)")
    print(f"{'=' * 60}")

    # Launch all 3 seeds
    for seed in SEEDS:
        case_dir = _case_dir(season, seed)
        if _is_complete(season, seed):
            print(f"  seed_{seed}: 已完成，跳过")
            continue
        print(f"  seed_{seed}: 启动中...")
        subprocess.run([
            sys.executable,
            str(PROJECT_ROOT / "tools" / "parallel" / "run_parallel.py"),
            "--run-dir", str(case_dir),
            "--case", "sa_sen_morris",
            "--mode", "sen",
            "--n-agents", str(N_AGENTS),
            "--no-wait",
        ], check=True)

    # Wait for all 3 to complete
    print(f"\n  等待完成...")
    while True:
        time.sleep(60)
        done = sum(1 for seed in SEEDS if _is_complete(season, seed))
        if done == 3:
            break
        # Show progress for running cases
        for seed in SEEDS:
            if not _is_complete(season, seed):
                c, f = _completed_failed(season, seed)
                print(f"    seed_{seed}: C={c} F={f}")

    # Report results
    print(f"\n  {season} 全部完成!")
    total_c, total_f = 0, 0
    for seed in SEEDS:
        c, f = _completed_failed(season, seed)
        total_c += c
        total_f += f
        rate = f / max(c, 1) * 100
        flag = " ✅" if rate == 0.0 else " ❌ formal gate requires 0 failures"
        print(f"    seed_{seed}: completed={c} failed={f} failure_rate={rate:.1f}%{flag}")
    overall = total_f / max(total_c, 1) * 100
    print(f"    总计: completed={total_c} failed={total_f} failure_rate={overall:.1f}%")
    return overall == 0.0


def cmd_run_all():
    """Run all 3 seasons sequentially."""
    all_ok = True
    for season in SEASONS:
        ok = cmd_run_season(season)
        if not ok:
            print(f"\n  ❌ {season} 存在模型失败，停止后续正式季次")
            all_ok = False
            break
    return all_ok


def cmd_postprocess():
    """Run multi-seed analysis for all 3 seasons."""
    for season, info in SEASONS.items():
        # Check all seeds complete
        if not all(_is_complete(season, s) for s in SEEDS):
            print(f"  {season}: 并非所有 seed 均完成，跳过")
            continue

        print(f"\n  {season}: 运行 multi-seed 分析...")
        out_dir = PROJECT_ROOT / "workspace" / "runs" / "morris_results" / season
        out_dir.mkdir(parents=True, exist_ok=True)

        # morris_multiseed is a standalone script (no subcommand), called directly
        cmd = [
            sys.executable, "-m", "src.sensitivity.morris_multiseed",
            "--output-profile", str(PROJECT_ROOT / info["contract"]),
            "--out-dir", str(out_dir),
            "--top-k", "15",
        ]
        for seed in SEEDS:
            cmd.extend(["--case-dir", str(_case_dir(season, seed))])
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"    错误: {result.stderr[-500:]}")
        else:
            print(f"    完成 → {out_dir}")
            # Show stability summary if available
            stability = out_dir / "morris_multiseed_stability.json"
            if stability.exists():
                s = json.loads(stability.read_text(encoding="utf-8"))
                decision = s.get("decision", "?")
                spearman = s.get("min_spearman", "?")
                print(f"    稳定性决策: {decision}")
                print(f"    最小 Spearman r: {spearman}")


def main():
    parser = argparse.ArgumentParser(description="T4 正式 Morris 敏感性分析")
    parser.add_argument("--run-all", action="store_true", help="运行所有 3 季节 (每季 3 seed)")
    parser.add_argument("--season", default=None, help="只运行指定季节 (XXQL2501/XXQL2502/XXQL2601)")
    parser.add_argument("--status", action="store_true", help="查看当前状态")
    parser.add_argument("--postprocess", action="store_true", help="后处理 (全部运行完成后)")
    args = parser.parse_args()

    if args.status:
        cmd_status()
    elif args.postprocess or args.run_all or args.season:
        raise SystemExit(
            "Retired execution entry: use tools/sa/run_all_sa_20260720.py. "
            "The legacy case root is not compatible with the frozen-runtime evidence contract."
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
