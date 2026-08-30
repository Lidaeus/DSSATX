# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

DSSAT × PEST++ automated calibration system for crop model parameters (primarily eggplant on tomato model TMGRO048). The system connects DSSAT v4.8's crop model with PEST++ (IES) to auto-calibrate genetic parameters and key environmental/initial conditions, producing deterministic simulations and publication-quality metrics.

**Key domain fact:** Eggplant uses DSSAT's tomato model files (TMGRO048.CUL/ECO/SPE) because DSSAT has no native eggplant model. The `crop` field distinguishes parameter values (tomato vs eggplant) while sharing the same model files.

## Commands

### Run Tests
```bash
python tests/test_migration.py               # migration verification tests
python -m pytest tests/                       # full suite (if pytest installed)
python -m pytest tests/test_publication_figures.py   # Python↔R figure-contract tests
```

### Calibration Workflow
```bash
# 1. Build calibration task (generates .pst/.tpl/.ins + run_manifest.yaml)
python src/calibration/build_pest.py \
  --mode eggplant_stage2 \
  --bounds-id eggplant_v14_20260405 --bounds-crop eggplant \
  --prefix <prefix> --noptmax 6 --ies-num-reals 80 \
  --batch DSSBatch.v48 --harvest-var CHPDT \
  --out-dir workspace/runs/<run_id>

# 2. Parallel execution (preferred)
python tools/parallel/run_parallel.py \
  --run-dir workspace/runs/<run_id> --case <prefix> \
  --mode ies --n-agents 6 --wait

# 3. Post-processing
python src/reporting/analyze_results.py --prefix <prefix> --run-dir <run_dir>

# 4. Deterministic simulation + metrics
python src/dssat/run_dssat.py --param-csv <csv> --batch DSSBatch.v48 --harvest-var CHPDT
python src/reporting/analyze_results.py --metrics-grid --prefix <prefix> --run-dir <det_dir> --batch DSSBatch.v48

# 5. Paper-figure pipeline (two-stage: Python exports frozen data, R renders)
python -m src.reporting.export_paper_data --run-id <run_id> \
  --comparison-csv <comparison.csv> --phi-csv <case.phi.actual.csv> \
  --trajectory-run-dir workspace/runs/<run_id> \
  --treatment-metadata-csv configs/figures/treatment_metadata_xxql2501.csv \
  --out-dir workspace/runs/<run_id>/paper_data
Rscript paper/R/make_all.R \
  --input-dir workspace/runs/<run_id>/paper_data \
  --out-dir workspace/runs/<run_id>/paper_figures
# Python run-time diagnostics only (no Fig/FigS numbers):
python src/reporting/plot_results.py --prefix <prefix>
```

### Bound Management
```bash
# Freeze bounds from proposal
python tools/freeze_bounds.py \
  --proposal <proposal.csv> --crop eggplant \
  --bounds-id <id> --notes "description"
```

### Utilities
```bash
python tools/clean_workspace.py          # clean temp DSSAT/PEST outputs
python tools/setup_workspace.py          # initialize directory structure
python tools/package_release.py --run-dir <run_dir>  # archive run package
```

## Architecture

### Template-Inject Pattern
PEST++ writes candidate parameters → `run_dssat.py` injects them into `.base` template files → generates DSSAT-readable `.CUL/.ECO/.SPE/.SOL` → DSSAT runs → output files read back via `.ins` instruction files → PEST++ computes objective function (phi).

### Code Organization

- `src/calibration/build_pest.py` — Main builder (~170KB). Parses `.base` files, generates PEST control files (.pst/.tpl/.ins). Contains all mode-specific logic (eggplant_stage2 handles phenology, growth, multi-harvest, process observations).
- `src/dssat/run_dssat.py` — DSSAT runner (~147KB). The "black box" PEST calls each iteration. `_format_to_width()` / `_format_to_width_preserve_space()` are critical — DSSAT `.CUL` files require exact 6-char fixed-width formatting.
- `src/common/param_registry.py` — Parameter registry with physical hard bounds (`PHYSICAL_BOUNDS` dict), default bound inference, and parameter grouping. Single source of truth for all parameter constraints.
- `src/sensitivity/` — Morris/Sobol sensitivity analysis tools (separate pipeline from calibration).
- `src/reporting/analyze_results.py` — Post-processing, metrics (RMSE/NRMSE/d-index), diagnostics.
- `src/reporting/figure_data.py` — Canonical tidy data contract + historical wide-output adapters for figures. Single source of truth for `comparison`/`trajectory`/`treatment_metadata` schemas and `VARIABLE_SPECS`.
- `src/reporting/export_paper_data.py` — Validates and freezes the renderer-neutral data bundle R consumes. **Must not import a plotting library** (enforced by tests).
- `src/reporting/plot_results.py` — Python run-time diagnostics entry only (SA trajectories, calibration progress). Produces `diagnostic_*`, never `Fig`/`FigS`.
- `paper/R/` — The only paper-figure renderer (`make_all.R` orchestrates `fig_*.R`; `common.R` holds theme/CLI/hash). See "Paper Figure Pipeline" below.
- `tools/parallel/` — Agent sandbox preparation and parallel PEST++ execution (manager/agent architecture).
- `tools/freeze_bounds.py` — Promotes bounds_proposal → bounds_frozen with metadata.

### Parameter Bound Layers (enforced strictly)

1. **Physical hard bounds** — in `src/common/param_registry.py:PHYSICAL_BOUNDS`. Absolute safety limits from DSSAT numerical stability.
2. **Baseline suggested bounds** — `data/parameter_registry/baseline/`
3. **SA candidate bounds** — `data/parameter_registry/bounds_proposals/` (proposals only, cannot be used directly)
4. **Frozen calibration bounds** — `data/parameter_registry/bounds_frozen/{crop}/` — **the only layer calibration may consume**

Inheritance chain: `baseline → proposal → frozen`. Calibration must specify `--bounds-id`. No auto-fallback to latest SA results.

### Data Flow

```
data/templates/genotype/          ← .CUL.base, .ECO.base, .SPE.base (template files with !Calibration markers)
data/templates/batch/             ← DSSBatch.v48 (treatment list)
data/raw/{weather,soil,experiments}/  ← input data (read-only)
data/parameter_registry/          ← bounds lifecycle
configs/runs/                     ← weight profiles
workspace/runs/{run_id}/          ← each run gets isolated directory
  ├── run_manifest.yaml           ← full run provenance
  ├── run_status.json             ← agent/manager state
  └── _agents/agent_*/            ← sandboxed DSSAT workers
```

### Parallel Execution Model

Manager/agent architecture. Each agent gets a complete copy of the run directory (file isolation). Agents work in `workspace/runs/{run_id}/_agents/agent_XX/`. PID files in `state/` subdirectory. Port auto-selection from 4010–4999.

### Key File Formats

- **Frozen bounds CSV** columns: `name, init, lower, upper, status, pargp, location, file, cultivar, ecotype, mode`
- **Parameter status**: `active` (calibrated), `fixed` (written but constant), `disabled` (excluded)
- **Run manifest YAML**: flat key-value pairs recording run_id, git_commit, bounds_id, batch_file, timestamps, command_line

## Important Conventions

- `FL-VS`: physical bounds (0.0, 300.0); default bounds (100.0, 140.0) — calibration allowed only when last-leaf/terminal-growth observations identify it (`src/common/param_registry.py` is the single source of truth; the E02 running contract of 2026-08-26 currently fixes it at 100.0)
- `XFINT`: physical bounds (0.0, 1.0); default working domain (0.10, 0.35) (`src/common/param_registry.py`)
- Observation groups: phenology (`PestEval.OUT`), growth (`PestGrow.OUT`), growth process (`PestTmtGrow.OUT`), multi-harvest (`PestHarvest.OUT`), joint season-end (`PestJoint.OUT`), soil water (`PestSoilWat.OUT`), N response (`PestNResponse.OUT`), W response (`PestWResponse.OUT`)
- DSSAT output path ambiguity: `Evaluate.OUT` may appear in workspace or `C:\DSSAT48\` — code checks both
- `.base` files use `!Calibration` comment markers to identify calibratable parameter lines
- `Workspace/*.py`: only a few files are redirect stubs into `src/` (`analyze_results.py`, `build_pest.py`, `run_dssat.py` via `runpy.run_module`; `plot_results.py` via `exec`). The rest are legacy one-off scripts slated for cleanup — do not add new tooling there.
- Branch and refactor-stage status are volatile by nature; consult the git repository and `docs/CHANGELOG.md` instead of this file.

## Paper Figure Pipeline (dual-track, strictly separated)

This project uses an **unmixable two-track figure system**. Read `docs/科研图表设计与开发计划.md` (canonical spec) and `paper/README.md` before touching anything figure-related.

| Track | Language | Purpose | Allowed outputs |
|---|---|---|---|
| Run diagnostics | Python | SA trajectories, calibration progress, failed members, parameter bounds, debugging | `diagnostic_*` only — **never** `Fig`/`FigS` |
| Paper / publication | R | Any figure that may enter the paper, supplement, or formal report | `Fig`/`FigS` + source CSV + metrics + manifest |

**Hard rules enforced by tests (`tests/test_publication_figures.py`):**
- R is the **only** paper-figure renderer. `src/reporting/export_paper_data.py` must not import `matplotlib`. `src/reporting/paper_figures.py` / `figure_style.py` were intentionally deleted — do not recreate a second Python figure implementation.
- R never reads DSSAT/PEST++ temp files and never guesses treatment→water/nitrogen mapping, iteration numbers, or data roles. It consumes only the frozen, hash-checked `paper_data` bundle.
- `make_all.R` only orchestrates; per-figure logic lives in `fig_*.R`; shared theme/CLI/hash live in `common.R`. One scientific question = one R module. Do not build a general plotting-library framework.

**The frozen data contract (`paper_data_manifest.json` gates entry — R verifies every artifact SHA-256):**
- `comparison.csv` — observed/simulated pairs. Required cols: `run_id,data_status,dataset_role,variable,variable_label,unit,treatment,time,time_label,observed,simulated,source_file`. Optional numeric: `date_code,year,doy,dap,harvest_number,observed_sd,observed_se,n_rep`. `dataset_role` ∈ {`calibration`,`validation`,`diagnostic`,`legacy_unsplit`}.
- `simulation_trajectory.csv` — daily DSSAT trajectories from `PlantGro.OUT`/`FreshWt.OUT`, `time`=DAP, `statistic`=`deterministic`. Separate from the pair table.
- `treatment_metadata.csv` — `treatment,treatment_label,water_level,nitrogen_level` (explicit, frozen; no inference from treatment number).
- `phi_ensemble.csv` — PEST++ Phi in iteration-realization long form (realization-level, **not** the reported mean column).

**Validation gate:** non-`science_validated` data is rejected by both Python and R unless both commands pass `--allow-unvalidated-demo`; output then uses a `DEMO_` prefix and a watermark and **cannot** be cited as a paper figure. Historical data is for interface/layout testing only.

**Dynamic-figure geometry rules (scientific, not cosmetic):**
- Continuous states (LAI, leaf/stem/aboveground mass): daily simulation as solid lines + observed points; error bars only when audited `observed_se` exists. Never feed sparse observed dates through `geom_smooth()` to fabricate a model trajectory — code checks `"geom_smooth" not in fig_selected_dynamics.R`.
- Incremental harvest: event lollipops/paired points — no smoothing layer.
- Cumulative harvest: **both** an event-step ordinary line (connecting simulated values at harvest dates) **and** a monotone cubic Hermite (`monoH.FC`) smooth alternative must be produced as a pair. The smooth is **visual only** — it never enters RMSE/NSE/d-index/Phi. If any interpolated cumulative node decreases, generation aborts (`monotone_cumulative_curve`).
- Residuals defined as `simulated - observed` (positive = overestimate); Q–Q is descriptive only, no mechanical pass/fail normality verdict.

**Water-nitrogen encoding (from `publication.json`, applied only to treatment-comparison/dynamic/management figures):** nitrogen→color (N3 `#C0392B` deep red, N2 `#E67E22` orange, N1 `#2980B9` blue, N0 `#707070` grey); water→shape (W3 circle 21, W2 square 22, W1 triangle 24, CK diamond 23). Sim vs obs distinguished by line/point, not extra line styles. Do not extend this dual encoding to Phi, posterior, or sensitivity figures.

**Style profile:** `configs/figures/publication.json` (`general_q1_v1`): R≥4.3, single column 89 mm, double 183 mm, max height 170 mm, 7 pt body / 8 pt panel labels, 0.5 pt axes, 1.0 pt data lines, 600 dpi review PNG, PDF/SVG/PNG outputs, color-blind-friendly. Per-figure output = PDF+SVG+PNG+source CSV (+metrics/QQ/summary CSV where applicable) and a `figure_manifest.json` (R/pkg versions, git commit/dirty, profile hash, all-artifact SHA-256). On Windows, SHA-256 uses system `certutil`; elsewhere `sha256sum`.

**Figure registry:** `configs/figures/figure_registry.csv` is the authoritative per-figure register (currently 23 rows: main Fig. 1–6, supplement Fig. S1–S8 incl. S1b/c/d, plus FigSa_summary, FigCondPerf, Fig4Cond, FigS4Cond, and one `diagnostic_*` entry). Status values in use: `pending_P4`, `pending_P5`, `pending_quality_bundle`, `r_demo_current_evidence`, `r_core_partial`, `r_core_implemented`, `r_core_implemented_demo_qa`. Do not fill empty figure numbers with placeholder/demo data — figures are gated on upstream scientific quality passes. Check the registry before adding a figure.

**R environment gotcha:** the dev machine's R is not on `PATH`; QA was done with an explicit R 4.5.2 path. R 4.6.0 is binary-incompatible with existing 4.5 user libraries — do not mix. Production should put the chosen R on `PATH` and pin package versions.

## Dependencies

- Python 3.13+; key packages: `pandas`, `numpy`, `pyemu`, `matplotlib`, `scipy` (initial ensemble, NSGA-III), `pymoo` (management optimization), `pyyaml` (tools) (see `requirements.txt`)
- R ≥ 4.3 for paper figures; packages: `ggplot2`, `patchwork`, `jsonlite`, `svglite` (no runtime install — `common.R` checks once)
- PEST++ binaries bundled in `pestpp-5.2.16-win/`
- DSSAT v4.8 expected at `C:\DSSAT48\` (DSCSM048.EXE)
- DSSAT uses CRGRO048 model (crgro model for tomato)

## Docs to read before editing sensitive areas

- **Figures/plotting:** `docs/科研图表设计与开发计划.md` (canonical figure spec, phases V0–V4, next-stage tasks T1–T4), `paper/README.md` (R pipeline contract), `configs/figures/figure_registry.csv` (current per-figure status).
- Research credibility / SA: `docs/项目状态与科研启动清单.md`, `docs/敏感性分析与率定用户指南.md`, `docs/权重设计方案改进提案.md`. Completed plans and superseded proposals are under `docs/archive/` and do not define current behavior.
- Project design / refactor: `项目重构规划.md`, `docs/DEVELOPER_GUIDE.md`, `docs/CHANGELOG.md`.
