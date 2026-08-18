# macOS DSSAT 氮响应曲线修改工作区

这是从 `D:\Tomato_Cal` 整理出的可移植研究工作区，目标是：在 macOS 上修改/编译 DSSAT 的氮响应部分，并用本项目的最佳参数和固定试验输入进行回归比较。

## 已包含内容

- `src/`：项目运行器、参数注入、多季节调度、氮响应接口、结果评价和绘图代码。
- `tools/`：率定、并行运行、输入检查和实验辅助脚本。
- `data/templates/`：`TMGRO048.CUL/ECO/SPE` 模板、`DSSAT48.INH/INP`、`DSSATPRO.v48` 和批处理模板。
- `data/user/experiments/`：best5 设计实际使用的 25SP、26SP 输入 bundle，包含 FileX、FileT、FileA、SOIL、天气、观测不确定度和输入审计文件。
- `configs/`：best5 设计、观测策略、处理水氮映射和绘图配置。
- `data/parameter_registry/bounds_frozen/eggplant/`：best5 使用的冻结参数边界。
- `workspace/runs/..._reference/`：best5 参数文件、设计 JSON、观测注册表和选择信息。
- `reference/best5_rendered/`：best5 确定性运行生成的 `CUL/ECO/SPE/SOIL` 及本地 DSSAT 输入副本，仅用于核对。

## 重要限制

本目录没有包含 DSSAT/CRGRO048 的 Fortran 源码，也没有包含可在 macOS 上运行的 DSSAT 或 PEST++ 二进制文件。当前项目中的 DSSAT 可执行文件是 Windows 版本，不能直接在 macOS 使用。需要从你拥有的 DSSAT 源码或授权发行版中准备 macOS 可执行文件。

项目使用 DSSAT 番茄模型 `TMGRO048` 模拟茄子；修改氮响应时应优先定位 DSSAT/CRGRO048 源码中的氮胁迫、氮吸收和组织氮响应例程，而不是只修改本项目的参数注入器。

## macOS 初始化

在本目录根部执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
export PYTHONPATH="$PWD"
```

如果只做输入注入和结果处理，可以先不安装 PEST++；如果要重新率定，需要准备 macOS 版 PEST++ 并按项目路径约定放置或配置。

## 用 best5 参数运行三季/两季诊断

best5 原率定设计包含 25SP 和 26SP。准备好可执行文件后，将其路径放入 `DSSAT_EXE_PATH`。项目运行器会把它复制到隔离运行目录，并以 DSSAT 运行时名称调用，不会覆盖系统 DSSAT：

```bash
export DSSAT_EXE_PATH="$PWD/external/dssat/DSCSM048"
mkdir -p workspace/runs/best5_macos_test
cp workspace/runs/e02_v2_joint25sp26sp_nosoil_nresp_200x4_loopback_20260802_det_best5_reference/best_member_params.csv \
   workspace/runs/best5_macos_test/best_member_params.csv

python src/calibration/run_multiseason.py \
  --design workspace/runs/e02_v2_joint25sp26sp_nosoil_nresp_200x4_loopback_20260802_det_best5_reference/design.json \
  --param-csv workspace/runs/best5_macos_test/best_member_params.csv \
  --prefix best5_macos_test --harvest-var CHPDT --keep-nitrogen-outputs
```

随后可以按项目现有流程生成比较表和诊断图。所有 FileX/FileT/FileA/SOIL 都由设计 JSON 中的 `data/user/experiments/...` 路径读取。

## 建议的氮响应修改流程

1. 将 DSSAT/CRGRO048 源码放入 `external/dssat_source/`，保留原始版本和修改版本的 commit 或补丁。
2. 先用未修改源码运行 best5，保存 `workspace/runs/best5_macos_baseline/`。
3. 每次只改变一个氮响应机制或参数化公式，重新编译并写入新的 `external/dssat/<version>/`。
4. 设置新的 `DSSAT_EXE_PATH`，运行独立的 `workspace/runs/<version>_best5/`。
5. 比较 `metrics_summary.csv`、氮响应曲线、LAI/生物量动态和累计产量；不要只依据总 Phi 判断氮响应是否改善。

## 来源与可追溯性

输入来源为：`e02_v2_joint25sp26sp_nosoil_nresp_200x4_loopback_20260802` 的完成版 best5 确定性设计；具体文件哈希和输入元数据保存在 `reference/source_metadata/`。原始 Windows 项目仍保留在上一级目录，本工作区中的文件是副本。
