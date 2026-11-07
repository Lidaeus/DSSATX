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
        clean-smoke clean-build clean-runs clean-trash distclean

help: ## 显示本帮助
	@echo "Tomato_Cal macOS 任务入口（默认 python: $(PYTHON), FC: $(if $(FC),$(FC),未找到!), 并行: $(JOBS)）"
	@echo
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

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
