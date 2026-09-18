"""run_multiseason wrapper for the XFPHT/XFINT-DELETED genotype template.

The multiseason runner copies the shared genotype templates
(``TMGRO048.ECO`` / ``TMGRO048.ECO.base``) from ``data/templates/genotype``
into every localized ``_seasons/<season>`` directory before each model run
(run_multiseason.py genotype-template loop).  To run with XFPHT/XFINT truly
absent from the ecotype file — without touching the shared baseline — this
wrapper intercepts only those two file-name copies when their destination is a
``_seasons`` directory and substitutes the derived column-stripped template
pair in ``data/templates/genotype_noxfx_20260903/``.  Everything else is
delegated to :mod:`src.calibration.run_multiseason` unchanged.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NOXFX_DIR = ROOT / "data/templates/genotype_noxfx_20260903"
SUBSTITUTES = {
    "TMGRO048.ECO.base": NOXFX_DIR / "TMGRO048.ECO.base",
    "TMGRO048.ECO": NOXFX_DIR / "TMGRO048.ECO",
}

_original_copy2 = shutil.copy2


def _patched_copy2(src, dst, *args, **kwargs):
    try:
        name = Path(str(src)).name
        dst_str = str(dst).replace("\\", "/")
        if name in SUBSTITUTES and "/_seasons/" in dst_str:
            return _original_copy2(str(SUBSTITUTES[name]), dst, *args, **kwargs)
    except Exception:
        pass
    return _original_copy2(src, dst, *args, **kwargs)


shutil.copy2 = _patched_copy2

from src.calibration.run_multiseason import main  # noqa: E402

if __name__ == "__main__":
    sys.argv[0] = "run_multiseason.py"
    raise SystemExit(main())
