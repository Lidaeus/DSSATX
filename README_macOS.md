# Tomato_Cal · macOS 开发交接

开发包保留当前率定、敏感性分析、诊断和论文绘图源码，以及独立的 DSSAT-CSM 4.8.6.4 引擎 Git 仓库。默认引擎入口来自 V7-SLN r1，原始源码提交为 `502ddfb7edd596eee2ebdc7c259196dce78058d9`。V7 是功能面积氮扩叶与同化速率的小试。冒烟测试默认用 V7 引擎上的冻结 V6 兼容配置。四套 V7 对照配置单独提供。

## 1. 解压和安装

用 macOS 终端解压，保留目录内的两个隐藏 `.git`。建议将工程放在短的、无空格的目录，避免 DSSAT 旧式定宽路径字段截断。Apple Silicon 使用 arm64 终端与 Homebrew，Intel 使用 x86_64 工具链，Python、编译器和依赖使用同一架构。

```bash
mkdir -p ~/dev
tar -xzf ~/Downloads/Tomato_Cal_macOS_20261106.tar.gz -C ~/dev
cd ~/dev/Tomato_Cal_macOS_20261106

# Command Line Tools 仅需安装一次。完成弹出的安装后继续。
xcode-select --install
# 需要先按 https://brew.sh/ 安装并激活 Homebrew
brew install gcc cmake ninja python@3.13

python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

如果 Command Line Tools 已安装，直接执行 Homebrew 步骤。使用 `uname -m`、`python -V` 和 `gfortran --version` 核对环境。若 Homebrew 只提供带版本号的 gfortran，先用 `ls "$(brew --prefix gcc)"/bin/gfortran*` 查看，再将完整路径指定给下面的 `FC`。

## 2. 编译和验证

从包根目录运行以下命令。CMake 在 `.local` 下构建，引擎测试和生产文件分开。

```bash
ENGINE=subprojects/critical_n/dssat_csm_os_4864
FC="$(command -v gfortran)"  # 或填 Homebrew 的版本化编译器路径
cmake -S "$ENGINE" -B .local/build-v7 -G Ninja \
  -DCMAKE_Fortran_COMPILER="$FC" -DCMAKE_BUILD_TYPE=RELEASE \
  -DDYNAMIC_LINK=ON -DCMAKE_POLICY_VERSION_MINIMUM=3.5
cmake --build .local/build-v7 --parallel 6
file .local/build-v7/bin/dscsm048

python tools/portable_dssat.py native-tests \
  --build .local/build-v7 --out .local/native-tests-v7
python tools/portable_dssat.py smoke \
  --exe .local/build-v7/bin/dscsm048 --out .local/smoke-v7

python -m pytest -q tests/test_publication_figures.py \
  tests/test_line_endings_policy.py \
  subprojects/critical_n/tests/test_dilution_curve.py \
  subprojects/critical_n/tests/test_effective_biomass.py \
  subprojects/critical_n/tests/test_scheme_b_mass_balance.py
python "$ENGINE/research/n_diagnostics/test_contract.py"
```

冒烟入口复制独立输入，生成本地 `DSSATPRO.L48`，读取样例的 `NIntegration.nml`，启用阶段 5 和 R2。样例含 26SP 12 处理、土壤、天气、品种、试验管理、CO₂ 和土壤过程标准表。成功会写 `.local/smoke-v7/receipt.json`，确认 1512 条逐日账、分层净吸氮及三项 N/C 账残差。测试目录必须是新目录，每次复跑换一个 `--out`。需要详细日内追踪时加 `--trace`，会增加约百 MB 输出。

例如启用 V7 的功能面积氮二次扩叶信号

```bash
python tools/portable_dssat.py smoke \
  --exe .local/build-v7/bin/dscsm048 --config fixtures/v7-configs/area_shape2.nml \
  --out .local/smoke-v7-area
```

`fixtures/v7-26sp/comparison.csv` 是旧运行的 612 项实测和模拟配对证据。将新执行体用于评价或率定时，要按当前执行结果重新提取模拟值，保留既有观测定义、单位和日期。

交付前已在 Windows 上从包内源码全量编译，实际运行上述 Fortran 测试及 26SP 冒烟样例。首次 macOS 原生运行请以上述验证为准。历史工具中需要 Windows 安装或归档的测试仍保留，完整测试集有这些额外依赖。

## 3. 率定和出图

- `src/calibration/`、`src/dssat/`、`tools/parallel/` 是率定入口。PEST++ 请使用与 Mac 架构匹配的原生执行体，可按 [USGS PEST++ 源码与构建说明](https://github.com/usgs/pestpp) 安装。将 `pestpp-ies` 所在目录加到 `PATH`，或设置 `PESTPP_BIN_DIR` 指向该目录。包内并行管理器会据此寻找 `pestpp-ies`、`pestpp-glm` 或 `pestpp-sen`。
- 现有按日期命名的率定脚本、一些配置和 PEST 控制文件生成路径仍沿用 Windows 目录。移植实际批次时，需要检查 `.pst` 的模型命令和每个工作目录里的 DSSAT 配置，先单独验证正向调用，再启动多进程。包内已验证的是独立正向冒烟入口，macOS PEST++ 联合率定仍待实跑。冻结边界、率定目标和观测算子请继续遵循 [项目规则](AGENTS.md) 和 [氮机制研究约束](subprojects/critical_n/AGENTS.md)。
- `paper/R/` 是论文绘图入口，需要 R 和 `ggplot2`、`patchwork`、`jsonlite`、`svglite`。论文图使用经验证的冻结数据包，操作见 [论文图流水线](paper/README.md)。
- `research/n_diagnostics/` 位于引擎仓库，可重绘冻结诊断数据。若 Matplotlib 找不到系统中文字体，设置 `DSSAT_DIAGNOSTIC_FONT` 为本机已安装的中文字体文件。下面示例只读归档数据重绘，避免覆盖现有图册。

```bash
mkdir -p .local/atlas-r4
cp -R docs/handoff/n_response_diagnostic_atlas_20261103/data .local/atlas-r4/
cp -R docs/handoff/n_response_diagnostic_atlas_20261103/reference_data .local/atlas-r4/
python "$ENGINE/research/n_diagnostics/make_atlas.py" --render-only \
  --profile configs/figures/publication.json --out-dir .local/atlas-r4
```

现成图册见 [V15 S1](docs/handoff/v15_s1_diagnostic_atlas_20261104/atlas/diagnostic_atlas.pdf) 和 [r4 氮响应](docs/handoff/n_response_diagnostic_atlas_20261103/figures/diagnostic_atlas.pdf)。V15 S1 的冻结 Fortran 参考源码和构建记录位于 `subprojects/critical_n/vnext_v15_s1/`，独立于 4.8.6.4 引擎。其历史图册脚本保留用于追溯，完整重绘依赖原 Windows 回放数据和原执行体指纹。

## 4. Git 开发方式

解压后有两个可独立提交的仓库。

| 仓库 | 路径 | 版本管理 |
|---|---|---|
| 主项目 | 包根目录 | 从当前 Windows 工作目录筛选并提交的精简快照，包含当时在用的未提交代码与测试。原始 HEAD 和导入文件哈希见 `docs/handoff/source_snapshot.json`。主项目原有完整历史仍在原仓库。 |
| 引擎 | `subprojects/critical_n/dssat_csm_os_4864/` | 独立 Git 历史。保留 V7、V6、4.8.6.4 官方底座和诊断分支，macOS 兼容调整在交接分支。 |

```bash
git status --short --branch
git -C "$ENGINE" status --short --branch
git -C "$ENGINE" branch
git switch -c codex/my-mac-work
git -C "$ENGINE" switch -c codex/my-engine-work
```

在各自仓库提交和推送。交接包未预设远程地址。需要同步到 Git 服务时，为主项目快照及引擎分别配置自己的远程仓库，主项目快照的历史与原主仓库不同源。编译产物和运行输出建议留在 `.local/`，冻结的原生输入按原字节保管。主仓库目录下引擎由自己的 Git 管理，因此外层提交不包含引擎工作文件。

包内保留实验输入、参数边界、主要源码和测试、代表诊断证据及引擎历史。旧运行沙箱、率定 worker、全量历史输出、Windows 二进制、虚拟环境、编译缓存与论文图历史输出留在 Windows 原工作区。
