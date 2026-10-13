# DSSAT-CSM 本地编译环境搭建与自定义 Scheme B 编译验证报告

**报告日期**: 2026-10-13  
**执行主体**: Antigravity Coding Agent  
**目标系统**: DSSAT-CSM v4.8.2 / v4.8.6 / CRGRO048  
**产物目标**: 沙箱隔离环境下的自定义可执行文件 `subprojects/critical_n/bin/dscsm048_cnc.exe` 与基准可执行文件 `subprojects/critical_n/bin/dscsm048_vanilla.exe`

---

## 1. 任务背景与核心要求

本任务旨在建立本地 Fortran / CMake 编译环境，深入调研并接入 DSSAT 官方仓库中的测试套件，在严格不破坏生产环境 `C:\DSSAT48\DSCSM048.EXE` 的前提下，编译集成先前完成的 Scheme B 临界氮稀释补丁（`CROPGRO.for`, `PHOTO.for`, `SENES.for`）的自定义 DSSAT 可执行体，并全面验证其非破坏性、原生向后兼容性与数值稳定性。

### 核心约束清单
1. **严格生产环境隔离**：绝不覆盖或改动 `C:\DSSAT48\DSCSM048.EXE`；
2. **所有编译构建中间件及产物严格沙箱化**：组织在 `subprojects/critical_n/` 独立子目录下；
3. **原生 CTest 与官方批处理测试套件集成**：填补官方 CMake 缺少 `enable_testing()` 的空白，提供真正的 CTest 回归测试支持；
4. **官方测试与温室茄子/番茄用例双模式全面验证**；
5. **主项目现有测试 100% 保持通过**。

---

## 2. Windows 本地编译工具链探测与搭建

### 2.1 动态工具链探测与选型
为保证在不同环境下的可移植性，构建管道实现了多级自适应工具链探测（用户态 Winget、MSYS2、UCRT64、MinGW 以及系统 PATH）：

- **软件包**: `BrechtSanders.WinLibs.POSIX.UCRT` (Version `16.2.0-14.0.0-r1`)
- **部署路径**: `C:\Users\Lidaeus\AppData\Local\Microsoft\WinGet\Packages\BrechtSanders.WinLibs.POSIX.UCRT_Microsoft.Winget.Source_8wekyb3d8bbwe\mingw64\bin`
- **编译器版本**:
  - `gfortran`: GNU Fortran (MinGW-W64 x86_64-ucrt-posix-seh, built by Brecht Sanders) **16.2.0**
  - `gcc`: 16.2.0
  - `cmake`: 4.4.2
  - `ninja`: 1.13.2
  - `ctest`: 4.4.2

### 2.2 构建系统验证
DSSAT-CSM 官方源码原生支持 CMake。结合 Ninja 构建引擎，DSSAT 包含的全部 1074 个 Fortran 模块可在 ~40 秒内完成全量编译，增量重建仅需 ~1-2 秒。产出的二进制完全静态链接 Fortran 运行时，仅依赖系统 `KERNEL32.dll` 与 `UCRT`。

---

## 3. DSSAT 官方仓库测试套件调研与分析

### 3.1 官方仓库测试体系深度调研
对 DSSAT 官方开放源码仓库 `DSSAT/dssat-csm-os`（包括 `develop`, `CI`, `master`, `release` 分支及各版本标签）进行检索分析发现：
1. **官方原生 CMakeLists.txt 未启用 CTest**：官方 `CMakeLists.txt` 仅配置了可执行体生成与安装规则，原生未定义 `enable_testing()` 或 `add_test()`，直接运行 `ctest` 会提示 `No test configuration file found!`。
2. **官方基准测试依托 `Data/BatchFiles/` 批处理体系**：官方采用端到端田间实验批处理模拟作为回归测试标准。`Data/BatchFiles/` 内置了覆盖 45+ 种作物的标准实验批处理文件（如 `Tomato.v48`, `Maize.v48`, `Rice.v48`, `Potato.v48` 等），驱动各作物参考实验（FileX）。
3. **本工程补全原生 CTest 测试集成**：构建管道在 `setup_source_trees` 中自动向 `CMakeLists.txt` 注入 `enable_testing()` 和 `add_test()`，注册了包括可执行体入口验证、Tomato 官方基准、Maize 官方基准及温室实验在内的 4 个标准 CTest 测试用例，使 `ctest` 命令行工具完全可用。

### 3.2 官方源码历史语法缺陷修复（`OPSOILNI.for`）
在使用高版本编译器（GCC 16.2.0）进行严格运行时验证时，定位并修复了 DSSAT 官方源码中的一处 Fortran 格式描述符拼写缺陷：
- **故障位置**: `Soil/Inorganic_N/OPSOILNI.for` Line 139
- **原始代码**:
  ```fortran
  WRITE(FRMT2,'(A,I2.2,A)') 
  & '(T',SPACES,'X,"Total Inorganic N @dep(ppm):")'
  ```
- **故障现象**: 当 `N_LYR` 使得 `SPACES=52` 时，格式化为 `(T52X, ...)`，语法中同时包含 `T`（跳列）与 `X`（空格）导致 Fortran 运行时直接抛出 `Missing comma between descriptors` 崩溃。
- **修复措施**: 修正为标准格式描述符 `'(' , SPACES , 'X,"Total Inorganic N @dep(ppm):")'`，完全消除该隐患并保持 72 列定宽规范。

---

## 4. 自定义 Scheme B 补丁注入与编译

### 4.1 源码沙箱组织
在 `subprojects/critical_n/` 内部建立了清晰的子目录树：
- `dssat_csm/`：DSSAT-CSM 原生基线源码（含 `OPSOILNI.for` 健壮性修复与 CTest 套件注入）；
- `dssat_csm_cnc/`：集成 Scheme B 的自定义源码树；
- `build/baseline/`：基准 CMake / Ninja 构建缓存目录；
- `build/custom/`：自定义 Scheme B CMake / Ninja 构建缓存目录；
- `bin/`：最终产物目录；
  - `dscsm048_vanilla.exe` (14.22 MB) —— 本地编译的基准参考二进制
  - `dscsm048_cnc.exe` (14.24 MB) —— 带有 Scheme B 临界氮稀释机制的自定义二进制

### 4.2 补丁注入与 72 列定宽复核
依据 Phase 2 CROPGRO Scheme B 规范，向 `dssat_csm_cnc/Plant/CROPGRO/` 安全注入三大核心模块：
1. `PHOTO.for`：引入连续饱和光合适应因子 $S(NNI) \in [0.30, 1.05]$，平滑抑制奢享氮素过旺生长并维持胁迫光合底线；
2. `SENES.for`：引入叶衰老阀门调节器，强制 $LFSEN_{\text{actual}} \le 0.90 \cdot WLDOTN + 0.015 \cdot WTLF$，彻底阻断落叶雪崩死亡螺旋；
3. `CROPGRO.for`：动态计算植株有效生物量 $W_{\text{eff}}$ 与临界氮浓度 $N_c$，计算 $NNI$ 并路由传入 `PHOTO` 与 `SENES`。

经 `validate_fortran_fixed_format()` 静态检测：**所有修改代码行严格控制在 7–72 列内，违规数为 0**。

### 4.3 CROPGRO 光合计算分支机制（`MEPHO='L'` vs `MEPHO='C'`）
深入分析 CROPGRO 源码发现了关键架构细节：
- 当实验配置中的光合方法为 `L`（逐时叶片光合，调用 SPAM/H Canes，如 `XXQL2501.TMX` 默认配置）时，CROPGRO 在日循环中调用 `GET('SPAM', ...)` 获取光合量，**不经过日均冠层 PHOTO.for**。因此在 `MEPHO='L'` 下，Scheme B 二进制与原生基线产生 **100% 完全相同**的生理轨迹，体现出完美的向后兼容性；
- 当光合方法配置为 `C`（日均冠层光合，调用 `PHOTO.for`）时，Scheme B 连续光合门控 $S(NNI)$ 全面激活，在水氮各处理下产生平滑合理的生理轨迹分化（1342 行输出差异），数值求解极度平稳，无溢出或截断。

---

## 5. 基准测试与科学回归验证

通过自动化脚本 `subprojects/critical_n/scripts/build_and_verify_dssat.py` 执行全量对比测试：

### 5.1 原生 CTest 测试套件执行记录
在构建目录下直接执行 `ctest --output-on-failure`：
- **Vanilla 构建目录 (`build/baseline`)**: 4/4 passed (100%), 耗时 13.5s
  - `dssat_smoke_help` -> **PASSED** (0.10s)
  - `dssat_official_tomato` -> **PASSED** (1.29s)
  - `dssat_official_maize` -> **PASSED** (8.96s)
  - `dssat_greenhouse_simulation` -> **PASSED** (3.09s)
- **Scheme B 构建目录 (`build/custom`)**: 4/4 passed (100%), 耗时 18.8s
  - `dssat_smoke_help` -> **PASSED** (0.10s)
  - `dssat_official_tomato` -> **PASSED** (1.38s)
  - `dssat_official_maize` -> **PASSED** (13.99s)
  - `dssat_greenhouse_simulation` -> **PASSED** (3.30s)

### 5.2 官方多作物基准批处理测试集
| 实验批处理 | 模拟模型 | Vanilla 退出码 | Scheme B 退出码 | 运行耗时 | Summary 记录数 | 状态 |
|---|---|---|---|---|---|---|
| `Tomato.v48` (Florida 标准 8 处理) | CRGRO048 | 0 | 0 | ~1.0s | 12 | **PASS** |
| `Maize.v48` (玉米经典实验) | DEFAULT | 0 | 0 | ~14.5s | 80 | **PASS** |
| `Potato.v48` (马铃薯经典实验) | DEFAULT | 0 | 0 | ~9.0s | 59 | **PASS** |
| `Rice.v48` (水稻经典实验) | DEFAULT | 0 | 0 | ~8.0s | 73 | **PASS** |

> 注：非 CROPGRO 模型（玉米 CERES-Maize、马铃薯 SUBSTOR-Potato、水稻 CERES-Rice）在 Vanilla 与 Scheme B 下输出 100% 位一致，证明补丁对其他作物模型具备零侵入安全性。

### 5.3 温室茄子/番茄水氮梯度双模式实验（`XXQL2501.TMX`）
| 运行模式 | 光合方法 (`MEPHO`) | Vanilla 退出码 | Scheme B 退出码 | PlantGro 行数 | 生理响应表现 |
|---|---|---|---|---|---|
| **向后兼容模式** | `L` (Hourly SPAM) | 0 | 0 | 1497 | 与基线 100% 相同（零漂移） |
| **Scheme B 激活模式** | `C` (Canopy Daily) | 0 | 0 | 1497 | $S(NNI)$ 动态调节光合，平滑收敛 |

---

## 6. 环境隔离与主项目安全性核验

1. **生产环境二进制完整性检查**:
   - 目标文件: `C:\DSSAT48\DSCSM048.EXE`
   - 测试前 SHA-256: `92173d5f63bc60d58839630b9a29f57632a19b373cab0faa8ad70362d98f5c7a`
   - 测试后 SHA-256: `92173d5f63bc60d58839630b9a29f57632a19b373cab0faa8ad70362d98f5c7a`
   - **核验结论: 100% 一致，未发生任何覆盖或篡改**。
2. **子项目单元测试套件**:
   - 运行: `python -m pytest subprojects/critical_n/tests/`
   - 结果: **70 passed, 1 skipped, 0 failed**（包含新增的 CTest 套件、Tomato 基准及温室双模式真实仿真测试）。
3. **主项目回归与安全性测试**:
   - 运行: `python tests/test_migration.py` 与 `pytest tests/test_dssat_safety.py`
   - 运行: `pytest tests/test_publication_figures.py`
   - 结果: **全部通过（100% PASS）**。

---

## 7. 交付文件清单

1. **构建与验证复现脚本**:
   - `subprojects/critical_n/scripts/build_and_verify_dssat.py`：自适应探测编译器、同步源码、注入 CTest 套件、编译两款二进制并跑通回归测试套件。
2. **测试用例**:
   - `subprojects/critical_n/tests/test_dssat_compiler_and_binary.py`：测试工具链可用性、二进制文件属性、源码定宽合规性、CTest 执行、真实 Tomato 基准仿真与温室双模式仿真。
3. **编译产物**:
   - `subprojects/critical_n/bin/dscsm048_vanilla.exe` (14.22 MB)
   - `subprojects/critical_n/bin/dscsm048_cnc.exe` (14.24 MB)
4. **执行摘要元数据**:
   - `subprojects/critical_n/reports/build_verification_summary.json`
