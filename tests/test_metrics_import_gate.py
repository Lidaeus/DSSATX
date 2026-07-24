"""Import-gate: the P0-D metrics/evaluation modules must not import a plotting library.

Mirrors the gate enforced on ``src/reporting/export_paper_data.py`` in
``test_publication_figures.py``: these are data/metric modules, not renderers,
so they must never pull matplotlib/seaborn into a data-export path.
"""
import re
from pathlib import Path

# Match actual import statements of forbidden libraries.  We check ``import X``
# and ``from X import`` forms, not arbitrary mentions in docstrings/comments.
_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+([a-zA-Z_][\w.]*)\s+import|import\s+([a-zA-Z_][\w.]*))",
    re.MULTILINE,
)
_FORBIDDEN_PREFIXES = ("matplotlib", "seaborn", "pyplot")
_MODULES = [
    "src/reporting/metrics.py",
    "src/reporting/residual_diagnostics.py",
    "src/reporting/experiment_evaluation.py",
    "tools/reporting/evaluate_calibration_experiment.py",
]


def test_metrics_modules_do_not_import_plotting_libraries():
    repo_root = Path(__file__).resolve().parents[1]
    for rel in _MODULES:
        source = (repo_root / rel).read_text(encoding="utf-8")
        imported = {m.group(1) or m.group(2) for m in _IMPORT_RE.finditer(source)}
        for mod in imported:
            for prefix in _FORBIDDEN_PREFIXES:
                assert not mod.startswith(prefix), (
                    f"{rel} must not import {mod!r} (forbidden plotting library "
                    f"prefix {prefix!r}). These are metric/evaluation modules, not renderers."
                )
