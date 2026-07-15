# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

DSSAT × PEST++ automated calibration system for crop model parameters (primarily eggplant on tomato model TMGRO048). The system connects DSSAT v4.8's crop model with PEST++ (IES) to auto-calibrate genetic parameters and key environmental/initial conditions, producing deterministic simulations and publication-quality metrics.

**Key domain fact:** Eggplant uses DSSAT's tomato model files (TMGRO048.CUL/ECO/SPE) because DSSAT has no native eggplant model. The `crop` field distinguishes parameter values (tomato vs eggplant) while sharing the same model files.

## Commands

### Run Tests
```bash
python tests/test_migration.py          # migration verification tests
python -m pytest tests/                  # if pytest installed
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

# 5. Plotting
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

- `src/calibration/build_pest.py` — Main builder (~103KB). Parses `.base` files, generates PEST control files (.pst/.tpl/.ins). Contains all mode-specific logic (eggplant_stage2 handles phenology, growth, multi-harvest, process observations).
- `src/dssat/run_dssat.py` — DSSAT runner (~87KB). The "black box" PEST calls each iteration. `format_val()` is critical — DSSAT `.CUL` files require exact 6-char fixed-width formatting.
- `src/common/param_registry.py` — Parameter registry with physical hard bounds (`PHYSICAL_BOUNDS` dict), default bound inference, and parameter grouping. Single source of truth for all parameter constraints.
- `src/sensitivity/` — Morris/Sobol sensitivity analysis tools (separate pipeline from calibration).
- `src/reporting/analyze_results.py` — Post-processing, metrics (RMSE/NRMSE/d-index), diagnostics.
- `src/reporting/plot_results.py` — Visualization generation.
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

- `FL-VS` is always fixed at 100.0 (not a calibration parameter)
- `XFINT` constrained to 0.12–0.50 to avoid IPDMND risk
- Observation groups: phenology (`PestEval.OUT`), growth process (`PestTmtGrow.OUT`), multi-harvest (`PestHarvest.OUT`), joint season-end (`PestJoint.OUT`)
- DSSAT output path ambiguity: `Evaluate.OUT` may appear in workspace or `C:\DSSAT48\` — code checks both
- `.base` files use `!Calibration` comment markers to identify calibratable parameter lines
- Workspace scripts (`Workspace/*.py`) are stubs that redirect to `src/` via `exec()`
- The project is mid-refactor (phases 0–4). Current branch `recalib-v14-consistent` reflects phases 0–4 completion

## Dependencies

- Python 3.13+
- Key packages: `pandas`, `numpy`, `pyemu`, `matplotlib`
- PEST++ binaries bundled in `pestpp-5.2.16-win/`
- DSSAT v4.8 expected at `C:\DSSAT48\` (DSCSM048.EXE)
- DSSAT uses CRGRO048 model (crgro model for tomato)
