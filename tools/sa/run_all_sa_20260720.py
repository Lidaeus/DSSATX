"""三季完整敏感性分析 — 一键脚本.

用法:
  # 1. 构建所有案例
  python tools/sa/run_all_sa_20260720.py --build

  # 2. 运行所有案例 (按季节依次执行)
  python tools/sa/run_all_sa_20260720.py --run

  # 3. 一步到位 (构建 + 运行 + 后处理)
  python tools/sa/run_all_sa_20260720.py --all

  # 查看状态
  python tools/sa/run_all_sa_20260720.py --status

  # 仅后处理
  python tools/sa/run_all_sa_20260720.py --postprocess

案例矩阵（首层共 9 个）:
  XXQL2501/2502/2601: r=10 × 3 seeds。
  只有本层质量和稳定性审核未通过时，才另行批准下一层；本脚本不预建 r=20/30/40。

修复记录:
  - SA=2 统一 (土壤分析不再按处理分化)
  - IC=2 统一 (初始条件已统一)
  - SYMBI=N (非豆科, POTAS 列对齐)
  - SOIL.SOL 使用用户桌面版本
  - 批处理文件裸名重写 (修复 XXQL2502 MAKEFW)
"""

from __future__ import annotations

import argparse, hashlib, json, re, subprocess, sys, time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

BOUNDS = "data/parameter_registry/bounds_frozen/eggplant/eggplant_formal_multiseason_candidate_v3_20260720.csv"
SEEDS = [20260729, 20260812, 20260826]

# 首层分析案例；禁止在没有上一层证据的情况下批量预建扩展层。
ALL_JOBS = [
    # (season, r, bundle_name, contract_suffix)
    ("XXQL2501", 10, "xxql2501_sa_controlled_candidate_20260720", "xxql2501"),
    ("XXQL2502", 10, "xxql2502_sa_controlled_candidate_20260720", "xxql2502"),
    ("XXQL2601", 10, "xxql2601_sa_controlled_tn12_w1_candidate_20260721", "xxql2601"),
]

OUT_ROOT = PROJECT_ROOT / "workspace" / "runs" / "formal_morris_repro_v1"


def _case_dir(season: str, r: int, seed: int) -> Path:
    return OUT_ROOT / season / f"r{r:02d}" / f"seed_{seed}"


def _is_complete(case_dir: Path) -> bool:
    rec = case_dir / "sa_sen_morris.rec"
    return rec.exists() and "analysis complete" in rec.read_text(encoding="utf-8", errors="ignore")


def _completed_failed(case_dir: Path) -> tuple[int, int]:
    log = case_dir / "manager" / "panther_manager.stdout.log"
    if not log.exists():
        return 0, 0
    text = log.read_text(encoding="utf-8", errors="ignore")
    c = re.findall(r"C(\d+)", text)
    f = re.findall(r"F(\d+)", text)
    return int(c[-1]) if c else 0, int(f[-1]) if f else 0


# ---- BUILD ----

def cmd_build():
    """构建首层 9 个案例。"""
    import subprocess

    total = len(ALL_JOBS) * 3
    built = 0
    for season, r, bundle_suf, contract_suf in ALL_JOBS:
        out = str(OUT_ROOT / season / f"r{r:02d}")
        bundle = f"data/user/experiments/{bundle_suf}"
        contract = f"configs/sa/eggplant_formal_{contract_suf}_outputs_20260720.json"
        if (OUT_ROOT / season / f"r{r:02d}" / "formal_morris_manifest.json").exists():
            print(f"[SKIP] {season} r={r}: already built")
            built += 3
            continue
        print(f"[BUILD] {season} r={r:02d}")
        result = subprocess.run([
            sys.executable, str(PROJECT_ROOT / "tools" / "build_formal_morris.py"),
            "--bounds", BOUNDS, "--input-dir", bundle,
            "--output-profile", contract, "--out-root", out,
            "--seeds"] + [str(s) for s in SEEDS] + [
            "--morris-r", str(r), "--morris-p", "6",
        ], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  FAIL: {result.stderr[-300:]}")
            return False
        built += 3
        print(f"  OK ({built}/{total})")
    print(f"\n{built}/{total} cases built")
    return True


# ---- RUN ----

def cmd_run():
    """运行所有案例（按季节和r级别依次执行）."""
    for season, r, _, _ in ALL_JOBS:
        print(f"\n{'='*60}")
        print(f"运行 {season} r={r:02d} (3 seeds × 6 agents)")
        print(f"{'='*60}")

        for seed in SEEDS:
            d = _case_dir(season, r, seed)
            if _is_complete(d):
                print(f"  seed_{seed}: 已完成, 跳过")
                continue
            print(f"  seed_{seed}: 运行中...")
            result = subprocess.run([
                sys.executable, str(PROJECT_ROOT / "tools" / "parallel" / "run_parallel.py"),
                "--run-dir", str(d), "--case", "sa_sen_morris",
                "--mode", "sen", "--n-agents", "6", "--wait",
            ], capture_output=True, text=True)
            if result.returncode != 0:
                print(f"    ⚠️ rc={result.returncode}")

        # Report
        total_c, total_f = 0, 0
        for seed in SEEDS:
            c, f = _completed_failed(_case_dir(season, r, seed))
            total_c += c
            total_f += f
        rate = total_f / max(total_c, 1) * 100
        flag = "✅" if total_f == 0 else "❌"
        print(f"  {season} r={r:02d}: 完成 {total_c} 失败 {total_f} 失败率 {rate:.1f}% {flag}")
        if total_f:
            print("  正式门要求零失败；停止后续季次并保留现场供诊断。")
            return False
    return True


# ---- STATUS ----

def cmd_status():
    """显示所有案例状态."""
    for season, r, _, _ in ALL_JOBS:
        complete = sum(1 for s in SEEDS if _is_complete(_case_dir(season, r, s)))
        total_c, total_f = 0, 0
        count = 0
        for s in SEEDS:
            c, f = _completed_failed(_case_dir(season, r, s))
            total_c += c
            total_f += f
            if _is_complete(_case_dir(season, r, s)):
                count += 1
        exp = (r * (55 + 1)) * 3
        if count == 3:
            print(f"  {season} r={r:02d}: COMPLETE (C={total_c} F={total_f})")
        elif count > 0:
            print(f"  {season} r={r:02d}: PARTIAL {count}/3  C={total_c} F={total_f}")
        else:
            built = _case_dir(season, r, SEEDS[0]).exists()
            if built:
                print(f"  {season} r={r:02d}: READY (not started)")
            else:
                print(f"  {season} r={r:02d}: NOT BUILT")


# ---- POSTPROCESS ----

def cmd_postprocess():
    """后处理所有已完成的 r 级别."""
    for season, r, _, contract_suf in ALL_JOBS:
        if not all(_is_complete(_case_dir(season, r, s)) for s in SEEDS):
            continue
        contract = f"configs/sa/eggplant_formal_{contract_suf}_outputs_20260720.json"
        out = PROJECT_ROOT / "workspace" / "runs" / "morris_results_repro_v1" / season / f"r{r:02d}"
        out.mkdir(parents=True, exist_ok=True)
        print(f"  {season} r={r:02d}: 后处理...")
        cmd = [sys.executable, "-m", "src.sensitivity.morris_multiseed",
               "--output-profile", str(PROJECT_ROOT / contract),
               "--out-dir", str(out), "--top-k", "15"]
        for s in SEEDS:
            cmd.extend(["--case-dir", str(_case_dir(season, r, s))])
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            stab = out / "morris_multiseed_stability.json"
            if stab.exists():
                d = json.loads(stab.read_text(encoding="utf-8"))
                print(f"    稳定={d['ranking_stable']}  Spearman={d['minimum_pairwise_spearman']:.3f}  Jaccard={d['minimum_pairwise_top_k_jaccard']:.3f}")
        else:
            print(f"    ⚠️ {result.stderr[-200:]}")


# ---- MAIN ----

def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="三季完整 Morris 敏感性分析")
    parser.add_argument("--build", action="store_true", help="构建所有案例")
    parser.add_argument("--run", action="store_true", help="运行所有案例")
    parser.add_argument("--all", action="store_true", help="一步到位: 构建 + 运行 + 后处理")
    parser.add_argument("--status", action="store_true", help="查看状态")
    parser.add_argument("--postprocess", action="store_true", help="后处理")
    args = parser.parse_args()

    if args.all:
        if cmd_build() and cmd_run():
            cmd_postprocess()
    elif args.build:
        cmd_build()
    elif args.run:
        cmd_run()
    elif args.status:
        cmd_status()
    elif args.postprocess:
        cmd_postprocess()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
