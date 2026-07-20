"""Expand Morris trajectories for XXQL2502 and XXQL2601 (手动作业).

XXQL2502 水氮响应域不稳定 (Spearman 0.818 < 0.90, Jaccard 0.579 < 0.80)
XXQL2601 水氮响应域边界不稳定 (Jaccard 0.765 < 0.80)

增量为 r=20，30，40 三个级别。扩大的案例构建完成后，由用户手动运行。
（r=10 的旧案例保留不变，新案例使用独立的 out-root）

用法:
  python tools/sa/expand_morris_r_20260720.py --build    # 构建案例
  python tools/sa/expand_morris_r_20260720.py --status   # 查看状态
"""

from __future__ import annotations

import argparse, sys, re, os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

BOUNDS = "data/parameter_registry/bounds_frozen/eggplant/eggplant_formal_multiseason_candidate_v3_20260720.csv"
SEEDS = [20260729, 20260812, 20260826]
# 季节需要扩充
SEASONS_EXPAND = {
    "XXQL2502": {
        "contract": "configs/sa/eggplant_formal_xxql2502_outputs_20260720.json",
        "bundle": "data/user/experiments/xxql2502_sa_controlled_candidate_20260720",
    },
    "XXQL2601": {
        "contract": "configs/sa/eggplant_formal_xxql2601_outputs_20260720.json",
        "bundle": "data/user/experiments/xxql2601_sa_controlled_7t_candidate_20260720",
    },
}
# 轨迹级别: r=20 (保守), r=30 (推荐), r=40 (彻底)
R_LEVELS = [20, 30, 40]

OUT_ROOT = PROJECT_ROOT / "workspace" / "runs" / "formal_morris_expanded"


def _r_case_dir(season: str, seed: int, r: int) -> Path:
    return OUT_ROOT / season / f"r{r:02d}" / f"seed_{seed}"


def _is_complete(case_dir: Path) -> bool:
    rec = case_dir / "sa_sen_morris.rec"
    return rec.exists() and "analysis complete" in rec.read_text(encoding="utf-8", errors="ignore")


def cmd_build():
    """构建所有需要扩充的案例。"""
    import subprocess

    for season, info in SEASONS_EXPAND.items():
        for r in R_LEVELS:
            print(f"\n{'='*60}")
            print(f"构建 {season} r={r} (3 seeds)")
            print(f"{'='*60}")
            result = subprocess.run([
                sys.executable,
                str(PROJECT_ROOT / "tools" / "build_formal_morris.py"),
                "--bounds", BOUNDS,
                "--input-dir", info["bundle"],
                "--output-profile", info["contract"],
                "--out-root", str(OUT_ROOT / season / f"r{r:02d}"),
                "--seeds"] + [str(s) for s in SEEDS] + [
                "--morris-r", str(r),
                "--morris-p", "6",
            ], capture_output=False, text=True)
            if result.returncode != 0:
                print(f"  ❌ 构建失败 (rc={result.returncode})")
                return
    print(f"\n✅ 所有案例构建完成")
    _print_run_commands()


def cmd_status():
    """显示所有扩充案例的状态。"""
    for season in SEASONS_EXPAND:
        print(f"\n--- {season} ---")
        for r in R_LEVELS:
            for seed in SEEDS:
                d = _r_case_dir(season, seed, r)
                if not d.exists():
                    print(f"  r={r:02d} seed_{seed}: NOT BUILT")
                elif _is_complete(d):
                    print(f"  r={r:02d} seed_{seed}: COMPLETE")
                else:
                    log = d / "manager" / "panther_manager.stdout.log"
                    if log.exists():
                        t = log.read_text(encoding="utf-8", errors="ignore")
                        c = re.findall(r"C(\d+)", t)
                        f = re.findall(r"F(\d+)", t)
                        print(f"  r={r:02d} seed_{seed}: RUNNING C={c[-1] if c else 0} F={f[-1] if f else 0}")
                    else:
                        print(f"  r={r:02d} seed_{seed}: READY (not started)")


def _print_run_commands():
    """打印运行命令。"""
    print(f"\n{'='*60}")
    print("运行命令（在终端中执行，每个 case 约 15-30 分钟）")
    print(f"{'='*60}")
    print("\n# 推荐: 先跑 r=20，检查稳定性；若仍不稳定再跑 r=30")
    print()
    for season in SEASONS_EXPAND:
        for r in R_LEVELS:
            print(f"# {season} r={r}")
            for seed in SEEDS:
                d = _r_case_dir(season, seed, r)
                print(f"python tools/parallel/run_parallel.py --run-dir \"{d}\" --case sa_sen_morris --mode sen --n-agents 6 --wait")
            print()
    print("# 全部完成后，运行后处理:")
    print(f"python tools/sa/expand_morris_r_20260720.py --postprocess")


def cmd_postprocess():
    """对已完成的扩充案例运行 multi-seed 分析。"""
    import subprocess

    for season, info in SEASONS_EXPAND.items():
        for r in R_LEVELS:
            seeds_done = all(_is_complete(_r_case_dir(season, s, r)) for s in SEEDS)
            if not seeds_done:
                print(f"  {season} r={r}: seeds 未全部完成，跳过")
                continue
            print(f"\n  {season} r={r}: 运行 multi-seed 分析...")
            out_dir = PROJECT_ROOT / "workspace" / "runs" / "morris_results_expanded" / season / f"r{r:02d}"
            out_dir.mkdir(parents=True, exist_ok=True)
            cmd = [
                sys.executable, "-m", "src.sensitivity.morris_multiseed",
                "--output-profile", str(PROJECT_ROOT / info["contract"]),
                "--out-dir", str(out_dir),
                "--top-k", "15",
            ]
            for seed in SEEDS:
                cmd.extend(["--case-dir", str(_r_case_dir(season, seed, r))])
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                s = (out_dir / "morris_multiseed_stability.json")
                if s.exists():
                    import json
                    d = json.loads(s.read_text(encoding="utf-8"))
                    print(f"    稳定: {d['ranking_stable']}  Spearman={d['minimum_pairwise_spearman']:.3f}  Jaccard={d['minimum_pairwise_top_k_jaccard']:.3f}")
            else:
                print(f"    错误: {result.stderr[-300:]}")


def main():
    parser = argparse.ArgumentParser(description="扩充 XXQL2502/XXQL2601 Morris 轨迹")
    parser.add_argument("--build", action="store_true", help="构建所有扩充案例")
    parser.add_argument("--status", action="store_true", help="查看状态")
    parser.add_argument("--postprocess", action="store_true", help="后处理已完成的案例")
    args = parser.parse_args()

    if args.status:
        cmd_status()
    elif args.build or args.postprocess:
        raise SystemExit(
            "Retired bulk expansion entry: first complete and review r=10 with "
            "tools/sa/run_all_sa_20260720.py, then approve exactly one next level."
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
