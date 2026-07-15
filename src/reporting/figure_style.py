"""Shared publication figure profile and export helpers."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
from typing import Any, Iterator, Mapping

import matplotlib as mpl


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE = PROJECT_ROOT / "configs" / "figures" / "publication.json"


def mm_to_inches(value: float) -> float:
    return float(value) / 25.4


def load_figure_profile(path: str | Path | None = None) -> dict[str, Any]:
    source = Path(path) if path else DEFAULT_PROFILE
    profile = json.loads(source.read_text(encoding="utf-8"))
    required = {
        "profile_id",
        "column_width_mm",
        "double_column_width_mm",
        "font_size_pt",
        "raster_dpi",
        "formats",
        "palette",
    }
    missing = required - set(profile)
    if missing:
        raise ValueError(f"Figure profile missing fields: {sorted(missing)}")
    if float(profile["font_size_pt"]) < 5.0:
        raise ValueError("Final-size figure font must be at least 5 pt")
    if int(profile["raster_dpi"]) < 300:
        raise ValueError("Raster preview/export must be at least 300 dpi")
    return profile


@contextmanager
def publication_style(profile: Mapping[str, Any]) -> Iterator[None]:
    """Apply a compact, colour-safe, editable-vector Matplotlib style."""
    base = float(profile["font_size_pt"])
    axes_width = float(profile.get("axes_linewidth_pt", 0.5))
    family = list(profile.get("font_family") or ["Arial", "Helvetica", "DejaVu Sans"])
    settings = {
        "font.family": "sans-serif",
        "font.sans-serif": family,
        "font.size": base,
        "axes.labelsize": base,
        "axes.titlesize": base,
        "xtick.labelsize": base,
        "ytick.labelsize": base,
        "legend.fontsize": base,
        "axes.linewidth": axes_width,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": False,
        "xtick.direction": "out",
        "ytick.direction": "out",
        "xtick.major.width": axes_width,
        "ytick.major.width": axes_width,
        "xtick.major.size": 2.5,
        "ytick.major.size": 2.5,
        "lines.linewidth": float(profile.get("data_linewidth_pt", 1.0)),
        "lines.markersize": float(profile.get("marker_size_pt", 3.5)),
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.02,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "svg.fonttype": "none",
        "axes.unicode_minus": False,
    }
    with mpl.rc_context(settings):
        yield


def panel_label(ax, label: str, profile: Mapping[str, Any]) -> None:
    ax.text(
        -0.14,
        1.04,
        str(label),
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=float(profile.get("panel_label_size_pt", 8.0)),
        fontweight="bold",
        clip_on=False,
    )


def save_figure(
    fig,
    output_base: str | Path,
    profile: Mapping[str, Any],
    *,
    metadata: Mapping[str, str] | None = None,
) -> list[Path]:
    """Save vector masters and a high-resolution raster preview."""
    output_base = Path(output_base)
    output_base.parent.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for fmt in profile.get("formats", ["pdf", "svg", "png"]):
        fmt = str(fmt).lower().lstrip(".")
        target = output_base.with_suffix(f".{fmt}")
        kwargs: dict[str, Any] = {"metadata": dict(metadata or {})}
        if fmt in {"png", "tif", "tiff", "jpg", "jpeg"}:
            kwargs["dpi"] = int(profile["raster_dpi"])
            # Matplotlib's PNG backend only accepts selected metadata types.
            kwargs["metadata"] = {str(k): str(v) for k, v in (metadata or {}).items()}
        try:
            fig.savefig(target, **kwargs)
        except (TypeError, ValueError):
            kwargs.pop("metadata", None)
            fig.savefig(target, **kwargs)
        paths.append(target)
    return paths


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "DEFAULT_PROFILE",
    "load_figure_profile",
    "mm_to_inches",
    "panel_label",
    "publication_style",
    "save_figure",
    "sha256_file",
]
