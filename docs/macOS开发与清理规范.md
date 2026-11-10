# macOS 开发与清理规范

> 文档状态：当前规范（macOS 平台）
> 适用范围：`~/dev/Tomato_Cal`（macOS 部署形态）
> 配套入口：根目录 `Makefile`（`make help` 查看全部命令）

本规范定义 macOS 上的目录布局、垃圾文件边界和清理入口。与 Windows 时代的
`tools/clean_workspace.py`（CWD 语义）不同，macOS 统一使用 `make clean-*`。

## 1. 部署布局

```text
~/dev/
  Tomato_Cal/                          # 主项目仓库（git，短路径无空格）
    subprojects/critical_n/dssat_csm_os_4864/   # 引擎子仓库（独立 git）
    .venv/                             # Python 3.13 虚拟环境（gitignore）
    .local/                            # ← 可再生根 1：编译/冒烟/图册输出
    workspace/                         # ← 可再生根 2：率定运行与沙箱
  archive/dssatx-handoff-20261106/     # 交接冷归档（非 git）
    Tomato_Cal_macOS_20261106.tar.gz   # 原始压缩包 + sha256（唯一原始备份）
    verify_evidence/                   # Windows 侧编译/冒烟/单测回执与日志
```

## 2. 两根原则（垃圾边界）

**所有可再生产物只允许落在两个 gitignore 根目录内**，整目录可随时删除而不影响
仓库与科学证据：

| 目录 | 承载内容 | 主要来源 | 清理命令 |
|---|---|---|---|
| `.local/build-*` | CMake/Ninja 引擎构建树 | `make build` | `make clean-build` |
| `.local/smoke-*` | 26SP 冒烟输出（每次自动带时间戳新目录） | `make smoke` / `make smoke-config` | `make clean-smoke` |
| `.local/native-tests-*` | 引擎 Fortran 单测输出 | `make native-tests` | `make clean-smoke` |
| `.local/atlas-*` | 诊断图册重绘 scratch | README_macOS §3 图册流程 | `make clean-smoke` |
| `workspace/runs/<run_id>/` | 单次率定/SA 运行目录（含 `_agents/` 沙箱副本 ×N） | `build_pest.py` + `run_parallel.py` | `make clean-runs`（先归档） |
| `workspace/trash/<时间戳>/` | 被归档的旧运行目录（短期人工复核区） | `make clean-runs` | `make clean-trash`（永久删除） |

**关键体积来源**：`workspace/runs/<run_id>/_agents/agent_XX/` 是 run 目录的完整副本
× agent 数（默认 `cpu_count()-2`），一次多 agent IES 运行可轻松膨胀数 GB——这是
`make clean-runs` 存在的首要原因。运行结束时 `run_parallel.py --cleanup` 会删除
`_agents/`，但中断的运行会残留。

## 3. 证据类文件（永不落入可删区）

以下内容**不在**两个可再生根内，任何清理命令都不触碰：

- `data/user/experiments/<bundle_id>/` — 版本化输入包（原始字节，含 manifest）
- `data/templates/` 与 `data/parameter_registry/bounds_frozen/` — 基线模板与冻结边界
- `configs/` — 版本化运行配置与图表注册表
- `docs/handoff/` — 冻结的诊断证据与图册
- `fixtures/` — 冻结的对照输入与 `receipt.json`（`.gitattributes` 按字节保管）

注意：`workspace/runs/<run_id>/` 内部的 `run_manifest.yaml`、`ies_quality/`、
`paper_data/` 属于该次运行的证据链。`make clean-runs` 因此**先移入
`workspace/trash/` 而非直接删除**；确认证据已随 `tools/package_release.py` 导出
或不再需要后，再用 `make clean-trash` 永久清空。

## 4. 常用命令

```bash
make help            # 全部命令
make env             # 创建 .venv + 安装依赖（一次性）
make build           # 编译引擎 → .local/build-v7/bin/dscsm048
make test            # 核心 pytest 套件 + 引擎 contract 测试
make native-tests    # 引擎 Fortran 单测（自动新目录）
make smoke           # 26SP 冒烟（自动新目录，免除 README 手动换 --out 的负担）
make status          # 各可清理目录磁盘占用一览

make clean-smoke     # 删 .local/{smoke,native-tests,atlas}-*（完全可再生）
make clean-build     # 删 .local/build-*（完全可再生）
make clean-runs      # workspace/runs/* → workspace/trash/<时间戳>/
make clean-trash     # 永久清空 workspace/trash/
make distclean       # 以上全部 + pytest/pycache 缓存
```

冒烟工具要求输出目录必须不存在（`portable_dssat.py` 用 `mkdir(exist_ok=False)`
强制隔离），Makefile 的 `smoke`/`native-tests`/`smoke-config` 目标自动生成带
时间戳的新目录，直接重复执行即可。

## 5. 与既有工具的关系

- `tools/clean_workspace.py` — Windows 时代工具，按**当前工作目录**扫描 `.pst`
  并归档到 `./Calibration_Results/_runs/`。macOS 上运行目录已隔离到
  `workspace/runs/<run_id>/`，该工具不再适用（保留代码供追溯，勿在 macOS 调用）。
- `tools/parallel/run_parallel.py --cleanup` — 运行结束删除 `_agents/`；中断残留
  由 `make clean-runs` 兜底。
- `tools/calibration_retention.py` — subprojects 下 `native_trials/` 的压缩保留
  工具，作用域不同，与本规范互补。
- `tools/setup_workspace.py` — 目录骨架初始化（2026-11-07 修复：根路径此前指向
  `tools/`，现正确指向仓库根）。

## 6. 率定工作流的垃圾纪律

1. 每次 SA/率定运行使用唯一 `run_id`，输出固定在 `workspace/runs/<run_id>/`，
   不在仓库根散落任何 PEST/DSSAT 中间文件（`*.OUT`、`*.pst` 等已被 gitignore）。
2. 长批次运行结束、质量报告与 finalize 产物确认后，即可 `make clean-runs`
   归档 `_agents/` 沙箱；需要长期保留的 run 用 `tools/package_release.py`
   打包导出后再清理。
3. 定期 `make status` 检查占用；磁盘紧张时按 `clean-smoke → clean-build →
   clean-trash` 顺序回收（均不影响科学证据）。
