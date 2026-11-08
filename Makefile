# Tomato_Cal · macOS 开发任务入口
#
# 原则（两根原则）：所有可再生产物只落在 .local/（编译/冒烟/图册）和
# workspace/（率定运行/沙箱）。两者均被 .gitignore 忽略，整目录可删。
# 证据类文件（run_manifest.yaml、receipt.json、data/ 输入包、bounds_frozen）
# 永不落入可删区。详见 docs/macOS开发与清理规范.md。

SHELL := /bin/bash
.DEFAULT_GOAL := help

# ── 路径与工具变量 ────────────────────────────────────────────
ENGINE := subprojects/critical_n/dssat_csm_os_4864
BUILD  := .local/build-v7
EXE    := $(BUILD)/bin/dscsm048

# V15 S1（n_buffer 线，vendored 4.8.2.0）率定接线
V15SRC   := subprojects/critical_n/vnext_v15_s1/source
V15BUILD := .local/build-v15s1
V15EXE   := $(V15BUILD)/bin/dscsm048
V15ASSET := .local/v15s1-inputs

PYTHON := $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3.13; fi)
FC     := $(shell command -v gfortran 2>/dev/null)
NPROC  := $(shell sysctl -n hw.ncpu 2>/dev/null || echo 6)
JOBS   := $(shell echo $$(( $(NPROC) < 6 ? $(NPROC) : 6 )))
TS     := $(shell date +%Y%m%d_%H%M%S)

# README_macOS.md §2 列出的核心测试（macOS 无外部依赖部分）
PY_TESTS := tests/test_publication_figures.py \
            tests/test_line_endings_policy.py \
            subprojects/critical_n/tests/test_dilution_curve.py \
            subprojects/critical_n/tests/test_effective_biomass.py \
            subprojects/critical_n/tests/test_scheme_b_mass_balance.py

.PHONY: help env build native-tests smoke smoke-config test status \
        clean-smoke clean-build clean-runs clean-trash distclean \
        v15s1-assets v15s1-env smoke-ies v4root-build v4root-tests \
        s4-build s4-tests

# ── V15 S3（v4root 变体：v4-R2 联立根吸核）────────────────────
# 冻结 S1 源码 rsync 到 .local（可再生），叠加变体 overlay 后构建。
V4VAR   := subprojects/critical_n/n_buffer_v15/source/v15_s3_v4root
V4SRC   := .local/build-v15-s3-v4root-src
V4BUILD := .local/build-v15-s3-v4root

v4root-tests: ## 运行 v4root 变体 NUPTAK 原生属性测试（直连真实对象）
	bash $(V4VAR)/run_native_tests.sh $(CURDIR)/subprojects/critical_n/vnext_v15_s1/source

$(V4BUILD)/bin/dscsm048: $(V4VAR)/NUPTAK.for
	@rm -rf $(V4SRC)
	rsync -a --exclude '.DS_Store' \
	  subprojects/critical_n/vnext_v15_s1/source/ $(V4SRC)/
	cp $(V4VAR)/NUPTAK.for $(V4SRC)/Plant/CROPGRO/NUPTAK.for
	cmake -S $(V4SRC) -B $(V4BUILD) -G Ninja \
	  -DCMAKE_Fortran_COMPILER="$(FC)" -DCMAKE_BUILD_TYPE=RELEASE \
	  -DCMAKE_POLICY_VERSION_MINIMUM=3.5
	cmake --build $(V4BUILD) --parallel $(JOBS)
	@file $(V4BUILD)/bin/dscsm048
	@shasum -a 256 $(V4BUILD)/bin/dscsm048

v4root-build: $(V4BUILD)/bin/dscsm048 ## 构建 v15_s3_v4root 变体引擎（overlay 于冻结 S1 源码）

# ── V15 S4（nstate 变体：ψ* 融合氮状态）───────────────────────
# 冻结 S1 源码 + 双 overlay（S3 的 NUPTAK.for + 修改的 N_BUFFER_V2.f90）。
S4VAR   := subprojects/critical_n/n_buffer_v15/source/v15_s4_nstate
S4SRC   := .local/build-v15-s4-nstate-src
S4BUILD := .local/build-v15-s4-nstate

s4-tests: ## 运行 ψ* 融合状态原生属性测试
	bash $(S4VAR)/run_native_tests.sh

$(S4BUILD)/bin/dscsm048: $(S4VAR)/N_BUFFER_V2.f90 $(S4VAR)/NUPTAK.for
	@rm -rf $(S4SRC)
	rsync -a --exclude '.DS_Store' \
	  subprojects/critical_n/vnext_v15_s1/source/ $(S4SRC)/
	cp $(S4VAR)/NUPTAK.for $(S4SRC)/Plant/CROPGRO/NUPTAK.for
	cp $(S4VAR)/N_BUFFER_V2.f90 $(S4SRC)/Plant/CROPGRO/N_BUFFER_V2.f90
	cmake -S $(S4SRC) -B $(S4BUILD) -G Ninja \
	  -DCMAKE_Fortran_COMPILER="$(FC)" -DCMAKE_BUILD_TYPE=RELEASE \
	  -DCMAKE_POLICY_VERSION_MINIMUM=3.5
	cmake --build $(S4BUILD) --parallel $(JOBS)
	@file $(S4BUILD)/bin/dscsm048
	@shasum -a 256 $(S4BUILD)/bin/dscsm048

s4-build: $(S4BUILD)/bin/dscsm048 ## 构建 v15_s4_nstate 变体引擎（2×2 因子开关单二进制）

# ── V15 S1 率定接线 ────────────────────────────────────────────
# 编译 V15 S1 引擎并准备率定资产：.local/v15s1-inputs/dssat-std（平铺标准
# 数据 + DSSATPRO.L48.in）与带 NBUF 机制卡的 TMGRO048.SPE 基线（项目基线
# 原样 + 冻结卡值，不改动 data/templates 的冻结模板）。
v15s1-assets: $(V15EXE) $(V15ASSET)/TMGRO048.SPE.base
$(V15EXE):
	cmake -S $(V15SRC) -B $(V15BUILD) -G Ninja \
	  -DCMAKE_Fortran_COMPILER="$(FC)" -DCMAKE_BUILD_TYPE=RELEASE \
	  -DCMAKE_POLICY_VERSION_MINIMUM=3.5
	cmake --build $(V15BUILD) --parallel $(JOBS)
	@file $(V15EXE)
$(V15ASSET)/TMGRO048.SPE.base: $(V15ASSET)/dssat-std/DSSATPRO.L48.in
	@mkdir -p $(V15ASSET)
	{ cat data/templates/genotype/TMGRO048.SPE.base; \
	  printf '\n!*ORGAN NITROGEN RESERVES AND BUFFER DILUTION\n'; \
	  sed -n '174p' fixtures/v7-26sp/TMGRO048.SPE; } > $@
	@echo "NBUF SPE 基线：$@"
$(V15ASSET)/dssat-std/DSSATPRO.L48.in:
	@mkdir -p $(V15ASSET)/dssat-std
	cp $(V15SRC)/Data/*.CDE $(V15SRC)/Data/MODEL.ERR $@D/
	cp $(V15SRC)/Data/StandardData/*.SDA $(V15SRC)/Data/StandardData/*.WDA $@D/
	cp $(V15SRC)/Data/DSSATPRO.L48.in $@D/
	@echo "标准数据：$(V15ASSET)/dssat-std/"

# 导出 V15 S1 联合率定所需的环境变量（source 或 eval 使用）：
#   eval "$(make v15s1-env)"
v15s1-env: ## 输出 V15 S1 率定环境变量（eval "$(make v15s1-env)"）
	@echo 'export DSSAT_CUSTOM_EXE=$(CURDIR)/$(V15EXE);'
	@echo 'export DSSAT_STD_DATA_DIR=$(CURDIR)/$(V15ASSET)/dssat-std;'
	@echo 'export DSSAT_SPE_BASE=$(CURDIR)/$(V15ASSET)/TMGRO048.SPE.base;'
	@echo 'export PATH=$(CURDIR)/.venv/bin:$$PATH;'

# 50×4 IES 联合率定冒烟（xxql2601 sasc70 bundle + 20261106 冻结边界）。
# 用法：make smoke-ies [PREFIX=xxx] [REALS=50] [ITERS=4] [AGENTS=4]
V15ENV := PATH="$(CURDIR)/.venv/bin:$$PATH" \
          DSSAT_CUSTOM_EXE="$(CURDIR)/$(V15EXE)" \
          DSSAT_STD_DATA_DIR="$(CURDIR)/$(V15ASSET)/dssat-std" \
          DSSAT_SPE_BASE="$(CURDIR)/$(V15ASSET)/TMGRO048.SPE.base"
smoke-ies: v15s1-assets ## V15 S1 50×4 PEST++ IES 联合率定冒烟
	@test -x .venv/bin/python || { echo "先运行 make env"; exit 2; }
	@P=$(if $(PREFIX),$(PREFIX),macsmk$(if $(REALS),$(REALS),50)x$(if $(ITERS),$(ITERS),4)); \
	R=$${P}_$$(date +%Y%m%d_%H%M%S); \
	echo "run_id=$$R"; \
	env $(V15ENV) .venv/bin/python src/calibration/build_pest.py \
	  --mode eggplant_stage2 \
	  --bounds-id eggplant_26sp_cal25sp_val_cold_c31pst_noadat_80x4_20261106 \
	  --bounds-crop eggplant \
	  --input-dir data/user/experiments/xxql2601_final_sasc70_20261106 \
	  --prefix $$P --noptmax $(if $(ITERS),$(ITERS),4) \
	  --ies-num-reals $(if $(REALS),$(REALS),50) --random-seed 20261107 \
	  --batch DSSBatch.v48 --harvest-var CHPDT \
	  --out-dir workspace/runs/$$R && \
	env $(V15ENV) .venv/bin/python tools/parallel/run_parallel.py \
	  --run-dir workspace/runs/$$R --case $$P \
	  --mode ies --n-agents $(if $(AGENTS),$(AGENTS),4) --wait && \
	.venv/bin/python tools/check_run_quality.py --allow-fail \
	  --run-dir workspace/runs/$$R --prefix $$P

help: ## 显示本帮助
	@echo "Tomato_Cal macOS 任务入口（默认 python: $(PYTHON), FC: $(if $(FC),$(FC),未找到!), 并行: $(JOBS)）"
	@echo
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# ── 环境 ──────────────────────────────────────────────────────
env: ## 创建 .venv 并安装 requirements-dev.txt
	python3.13 -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/pip install -r requirements-dev.txt

# ── 构建与验证 ────────────────────────────────────────────────
build: $(EXE) ## 编译 DSSAT-CSM 4.8.6.4 引擎（Ninja/RELEASE）
$(EXE):
ifndef FC
	$(error 未找到 gfortran。请先 brew install gcc，或在调用时指定 FC=/path/to/gfortran)
endif
	cmake -S $(ENGINE) -B $(BUILD) -G Ninja \
	  -DCMAKE_Fortran_COMPILER="$(FC)" -DCMAKE_BUILD_TYPE=RELEASE \
	  -DDYNAMIC_LINK=ON -DCMAKE_POLICY_VERSION_MINIMUM=3.5
	cmake --build $(BUILD) --parallel $(JOBS)
	@file $(EXE)

native-tests: build ## 引擎 Fortran 单元测试（输出 .local/native-tests-$(TS)）
	$(PYTHON) tools/portable_dssat.py native-tests --build $(BUILD) --out .local/native-tests-$(TS)
	@echo "native-tests 输出：.local/native-tests-$(TS)"

smoke: build ## 26SP 冒烟测试（冻结 V6 兼容配置，输出自动带时间戳）
	$(PYTHON) tools/portable_dssat.py smoke --exe $(EXE) --out .local/smoke-$(TS)
	@echo "smoke 输出：.local/smoke-$(TS)（成功标志 receipt.json）"

smoke-config: build ## 冒烟测试自定义配置：make smoke-config CONFIG=fixtures/v7-configs/area_shape2.nml
	@test -n "$(CONFIG)" || { echo "用法：make smoke-config CONFIG=<nml 路径>"; exit 2; }
	$(PYTHON) tools/portable_dssat.py smoke --exe $(EXE) --config $(CONFIG) --out .local/smoke-$(TS)
	@echo "smoke 输出：.local/smoke-$(TS)"

test: ## 运行核心 pytest 套件 + 引擎 contract 测试
	$(PYTHON) -m pytest -q $(PY_TESTS)
	$(PYTHON) $(ENGINE)/research/n_diagnostics/test_contract.py

# ── 磁盘状态 ──────────────────────────────────────────────────
status: ## 显示各可清理目录的磁盘占用
	@echo "── 可再生产物（可安全清理）──"
	@for d in .local/build-* .local/smoke-* .local/native-tests-* .local/atlas-* workspace/runs workspace/trash; do \
	  if [ -e "$$d" ]; then du -sh "$$d"; fi; \
	done; \
	total=$$(du -shc .local/build-* .local/smoke-* .local/native-tests-* .local/atlas-* workspace/runs workspace/trash 2>/dev/null | tail -1 | cut -f1); \
	echo "── 合计: $${total:-0}（make clean-* / distclean 可回收）──"

# ── 清理（两根原则：只清 .local/ 与 workspace/）──────────────
clean-smoke: ## 删除 .local/ 下冒烟/单测/图册输出（完全可再生）
	@rm -rf .local/smoke-* .local/native-tests-* .local/atlas-*
	@echo "已清理 .local/{smoke,native-tests,atlas}-*"

clean-build: ## 删除 .local/ 下引擎构建树（完全可再生）
	@rm -rf .local/build-*
	@echo "已清理 .local/build-*"

clean-runs: ## 将 workspace/runs/* 归档进 workspace/trash/<时间戳>/（不直删率定证据）
	@if [ -d workspace/runs ] && [ -n "$$(find workspace/runs -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then \
	  ts=$$(date +%Y%m%d_%H%M%S); \
	  mkdir -p "workspace/trash/$$ts"; \
	  find workspace/runs -mindepth 1 -maxdepth 1 -exec mv {} "workspace/trash/$$ts/" \; ; \
	  echo "已将 workspace/runs/* 归档到 workspace/trash/$$ts/"; \
	else \
	  echo "workspace/runs 为空，无需归档"; \
	fi

clean-trash: ## 永久清空 workspace/trash/（清空前请确认证据已随 run 包导出）
	@rm -rf workspace/trash && mkdir -p workspace/trash
	@echo "已清空 workspace/trash/"

distclean: clean-smoke clean-build clean-runs clean-trash ## 回收全部可再生空间（含 pytest/pycache 缓存）
	@rm -rf .pytest_cache
	@find src tests tools Workspace -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
	@echo "distclean 完成"
