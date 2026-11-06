"""
Agrometeorological Heatmap Characterization: 25SP vs 26SP
Compares Daily Maximum Temperature, Minimum Temperature, and Solar Radiation
between the 2025 Spring (25SP) and 2026 Spring (26SP) eggplant growing seasons.

Features:
- Exact growing season bounds extracted from TMX files (XXQL2501.TMX, XXQL2601.TMX)
- Colormaps exactly calibrated to the reference publication figure
- Non-growing season converted to luminance grayscale after color mapping
- Supports both Dekad (10-day / 旬) chunky-grid and Daily (逐日) high-resolution formats
- Supports 3-panel (TMAX, TMIN, SRAD) and 6-panel (+TMEAN, DTR, RHUM) layouts
- Exports high-resolution PNG (600 DPI), SVG, and PDF
"""

import os
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.patches import Rectangle


def parse_tmx_dates(tmx_path: str):
    """Extract PDATE and final HDATE from TMX file."""
    pdate = None
    hdates = []
    with open(tmx_path, 'r', encoding='utf-8', errors='ignore') as f:
        section = None
        for line in f:
            line_str = line.strip()
            if line_str.startswith('*PLANTING DETAILS'):
                section = 'PLANTING'
                continue
            elif line_str.startswith('*HARVEST DETAILS'):
                section = 'HARVEST'
                continue
            elif line_str.startswith('*') and section:
                section = None
                
            if section == 'PLANTING' and line_str and not line_str.startswith('@'):
                parts = line_str.split()
                if len(parts) >= 2 and pdate is None:
                    pdate = int(parts[1])
            elif section == 'HARVEST' and line_str and not line_str.startswith('@'):
                parts = line_str.split()
                if len(parts) >= 2:
                    try:
                        hdates.append(int(parts[1]))
                    except ValueError:
                        pass
                        
    if pdate is None:
        raise ValueError(f"Could not find PDATE in {tmx_path}")
    final_hdate = max(hdates) if hdates else pdate + 120
    first_hdate = min(hdates) if hdates else None
    return pdate, final_hdate, first_hdate


def load_weather_data(wth_path: str):
    """Load and parse DSSAT WTH file."""
    with open(wth_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = [l.strip().split() for l in f if l.strip() and not l.startswith(('$', '@', '*', '!'))]
    
    # Skip the first non-comment line if it's the station header (LAT, LONG, etc.)
    if len(lines) > 0 and len(lines[0]) > 6:
        lines = lines[1:]
        
    df = pd.DataFrame(lines, columns=['DATE', 'SRAD', 'TMAX', 'TMIN', 'RAIN', 'RHUM'])
    for col in ['SRAD', 'TMAX', 'TMIN', 'RAIN', 'RHUM']:
        df[col] = df[col].astype(float)
        
    df['YEAR'] = df['DATE'].str[:4].astype(int)
    df['DOY'] = df['DATE'].str[4:].astype(int)
    df['DATETIME'] = pd.to_datetime(df['DATE'], format='%Y%j')
    df['MONTH'] = df['DATETIME'].dt.month
    df['DAY'] = df['DATETIME'].dt.day
    
    # Calculated variables
    df['TMEAN'] = (df['TMAX'] + df['TMIN']) / 2.0
    df['DTR'] = df['TMAX'] - df['TMIN']
    
    # Dekad definition: 1 = days 1-10, 2 = days 11-20, 3 = days 21-end
    def get_dekad(day):
        return 1 if day <= 10 else (2 if day <= 20 else 3)
        
    df['DEKAD'] = df['DAY'].apply(get_dekad)
    df['DEKAD_ID'] = (df['MONTH'] - 1) * 3 + df['DEKAD']
    return df


def get_reference_colormaps():
    """Build colormaps matching the reference figure."""
    # Maximum temperature: light yellow -> warm gold -> orange -> coral red -> dark mahogany
    cmap_tmax = mcolors.LinearSegmentedColormap.from_list(
        'ref_tmax', ['#fef9bc', '#f3d162', '#e69252', '#cd524b', '#71372e', '#1d1a02']
    )
    # Minimum temperature: navy blue -> steel/slate blue -> neutral cream -> apricot/salmon -> deep coral
    cmap_tmin = mcolors.LinearSegmentedColormap.from_list(
        'ref_tmin', ['#1e1d70', '#295596', '#4b89a6', '#f0ebd8', '#e3b998', '#d35400']
    )
    # Solar radiation: deep indigo -> slate gray -> taupe -> olive khaki -> warm yellow -> radiant yellow
    cmap_srad = mcolors.LinearSegmentedColormap.from_list(
        'ref_srad', ['#002456', '#37466b', '#686a71', '#958f77', '#c9b968', '#fce748']
    )
    # Mean temperature: blue -> cream -> red (diverging / soft)
    cmap_tmean = mcolors.LinearSegmentedColormap.from_list(
        'ref_tmean', ['#313695', '#74add1', '#ffffbf', '#f46d43', '#a50026']
    )
    # Diurnal temperature range: soft cyan -> light yellow -> purple/violet
    cmap_dtr = mcolors.LinearSegmentedColormap.from_list(
        'ref_dtr', ['#e0f3f8', '#fee090', '#f46d43', '#67001f']
    )
    # Relative humidity: mint green -> deep navy
    cmap_rhum = mcolors.LinearSegmentedColormap.from_list(
        'ref_rhum', ['#e0f3f8', '#66c2a5', '#3288bd', '#5e4fa2']
    )
    
    return {
        'TMAX': (cmap_tmax, mcolors.Normalize(vmin=10, vmax=45), [15, 25, 35, 45], 'Maximum temperature (°C)'),
        'TMIN': (cmap_tmin, mcolors.Normalize(vmin=0, vmax=25), [0, 10, 20], 'Minimum temperature (°C)'),
        'SRAD': (cmap_srad, mcolors.Normalize(vmin=0, vmax=18), [0, 5, 10, 15], 'Solar radiation (MJ/m²·d)'),
        'TMEAN': (cmap_tmean, mcolors.Normalize(vmin=10, vmax=35), [10, 20, 30], 'Mean temperature (°C)'),
        'DTR': (cmap_dtr, mcolors.Normalize(vmin=5, vmax=25), [5, 15, 25], 'Diurnal temp. range (°C)'),
        'RHUM': (cmap_rhum, mcolors.Normalize(vmin=40, vmax=100), [40, 60, 80, 100], 'Relative humidity (%)')
    }


def to_grayscale(rgba):
    """Convert RGB array to perceptual luminance grayscale."""
    gray = 0.299 * rgba[..., 0] + 0.587 * rgba[..., 1] + 0.114 * rgba[..., 2]
    out = np.copy(rgba)
    for i in range(3):
        out[..., i] = gray
    return out


def plot_dekad_heatmaps(df, gs_info, out_path, panel_mode='3panel', dpi=600):
    """
    Plot Dekad (10-day / 旬) chunky-grid heatmaps exactly matching the reference style.
    
    panel_mode: '3panel' (TMAX, TMIN, SRAD) or '6panel' (adds TMEAN, DTR, RHUM)
    """
    colormaps = get_reference_colormaps()
    vars_to_plot = ['TMAX', 'TMIN', 'SRAD'] if panel_mode == '3panel' else ['TMAX', 'TMIN', 'SRAD', 'TMEAN', 'DTR', 'RHUM']
    
    # Months 1 to 7 (Jan to Jul) -> 21 dekads
    n_dekads = 21
    dekad_range = list(range(1, n_dekads + 1))
    dekad_df = df[df['DEKAD_ID'] <= n_dekads].groupby(['YEAR', 'DEKAD_ID'])[vars_to_plot].mean().reset_index()
    
    years = [2026, 2025]
    year_labels = ['26SP (2026)', '25SP (2025)']
    # Colors for Y-axis labels like the reference figure
    y_colors = ['#C0392B', '#2980B9']  # 26SP red/burgundy, 25SP blue
    
    # Map DOY to DEKAD_ID for growing season markers
    gs_dekads = {}
    for y, (p_doy, h_doy, first_h_doy) in gs_info.items():
        p_dt = pd.to_datetime(f"{y}{p_doy:03d}", format='%Y%j')
        h_dt = pd.to_datetime(f"{y}{h_doy:03d}", format='%Y%j')
        p_dekad = (p_dt.month - 1) * 3 + (1 if p_dt.day <= 10 else (2 if p_dt.day <= 20 else 3))
        h_dekad = (h_dt.month - 1) * 3 + (1 if h_dt.day <= 10 else (2 if h_dt.day <= 20 else 3))
        gs_dekads[y] = (p_dekad, h_dekad)
        
    n_rows = 1 if panel_mode == '3panel' else 2
    n_cols = 3
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(14.5, 4.2 if panel_mode == '3panel' else 7.8), dpi=dpi)
    axes = np.array(axes).reshape(n_rows, n_cols)
    
    month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul']
    month_mid_dekads = [1.5, 4.5, 7.5, 10.5, 13.5, 16.5, 19.5]  # centers for month labels (0-indexed)
    
    for idx, var_name in enumerate(vars_to_plot):
        r_ax = idx // n_cols
        c_ax = idx % n_cols
        ax = axes[r_ax, c_ax]
        
        cmap, norm, ticks, label = colormaps[var_name]
        
        mat = np.full((len(years), n_dekads), np.nan)
        is_gs = np.full((len(years), n_dekads), False)
        
        for r, y in enumerate(years):
            sub = dekad_df[dekad_df['YEAR'] == y].set_index('DEKAD_ID')
            p_dek, h_dek = gs_dekads[y]
            for c, d in enumerate(dekad_range):
                if d in sub.index:
                    mat[r, c] = sub.loc[d, var_name]
                    if p_dek <= d <= h_dek:
                        is_gs[r, c] = True
                        
        rgba = cmap(norm(mat))
        gray_rgba = to_grayscale(rgba)
        
        # Mask non-growing season with grayscale
        mask = (~is_gs) & (~np.isnan(mat))
        for i in range(3):
            rgba[..., i] = np.where(mask, gray_rgba[..., i], rgba[..., i])
            
        # Draw cells
        for r in range(len(years)):
            for c in range(n_dekads):
                if np.isnan(mat[r, c]):
                    color = (0.95, 0.95, 0.95, 1.0)
                else:
                    color = rgba[r, c]
                rect = Rectangle((c, r), 1, 1, facecolor=color, edgecolor='#333333', linewidth=0.5)
                ax.add_patch(rect)
                
        # Draw growing season boundary highlights
        for r, y in enumerate(years):
            p_dek, h_dek = gs_dekads[y]
            ax.plot([p_dek - 1, p_dek - 1], [r, r + 1], color='#D32F2F', linewidth=1.6, linestyle='--')
            ax.plot([h_dek, h_dek], [r, r + 1], color='#D32F2F', linewidth=1.6, linestyle='--')
            
        ax.set_xlim(0, n_dekads)
        ax.set_ylim(len(years), 0)
        
        # Y-axis ticks & labels
        if c_ax == 0:
            ax.set_yticks([0.5, 1.5])
            ax.set_yticklabels(year_labels, fontsize=9.5, fontweight='bold')
            for tick_label, color in zip(ax.get_yticklabels(), y_colors):
                tick_label.set_color(color)
        else:
            ax.set_yticks([])
            
        # X-axis ticks & labels
        ax.set_xticks(month_mid_dekads)
        ax.set_xticklabels(month_names, fontsize=8.5)
        ax.set_xticks(range(n_dekads + 1), minor=True)
        ax.tick_params(which='minor', length=2.5, color='#777777')
        ax.tick_params(which='major', length=0)
        
        if r_ax == n_rows - 1:
            ax.set_xlabel('Month', fontsize=9.5, fontweight='bold', labelpad=4)
            
        ax.set_title(label, fontsize=10.5, fontweight='bold', pad=32)
        
        cax = ax.inset_axes([0.15, 1.07, 0.70, 0.055])
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
        cb = fig.colorbar(sm, cax=cax, orientation='horizontal')
        cb.set_ticks(ticks)
        cb.ax.tick_params(labelsize=7.5, pad=1.5)
        cb.outline.set_linewidth(0.4)
        
    fig.suptitle('Agroclimatic Characterization & Growing Season Comparison (25SP vs 26SP)',
                 fontsize=13, fontweight='bold', y=1.02 if panel_mode == '3panel' else 0.99)
                 
    plt.tight_layout()
    plt.savefig(out_path, bbox_inches='tight', dpi=dpi)
    pdf_path = str(out_path).replace('.png', '.pdf')
    svg_path = str(out_path).replace('.png', '.svg')
    plt.savefig(pdf_path, bbox_inches='tight')
    plt.savefig(svg_path, bbox_inches='tight')
    plt.close()
    print(f"Dekad plot saved to: {out_path} (and .pdf/.svg)")


def plot_daily_heatmaps(df, gs_info, out_path, max_doy=205, dpi=600):
    """Plot Daily high-resolution heat-stripes."""
    colormaps = get_reference_colormaps()
    vars_to_plot = ['TMAX', 'TMIN', 'SRAD']
    
    doy_range = np.arange(1, max_doy + 1)
    years = [2026, 2025]
    year_labels = ['26SP (2026)', '25SP (2025)']
    y_colors = ['#C0392B', '#2980B9']
    
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5), dpi=dpi)
    month_starts = [1, 32, 60, 91, 121, 152, 182]
    month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul']
    
    for ax, var_name in zip(axes, vars_to_plot):
        cmap, norm, ticks, label = colormaps[var_name]
        
        mat = np.full((len(years), len(doy_range)), np.nan)
        is_gs = np.full((len(years), len(doy_range)), False)
        
        for r, y in enumerate(years):
            sub = df[df['YEAR'] == y].set_index('DOY')
            p_start, p_end, _ = gs_info[y]
            for c, doy in enumerate(doy_range):
                if doy in sub.index:
                    mat[r, c] = sub.loc[doy, var_name]
                    if p_start <= doy <= p_end:
                        is_gs[r, c] = True
                        
        rgba = cmap(norm(mat))
        gray_rgba = to_grayscale(rgba)
        
        mask = (~is_gs) & (~np.isnan(mat))
        for i in range(3):
            rgba[..., i] = np.where(mask, gray_rgba[..., i], rgba[..., i])
        rgba[np.isnan(mat)] = [0.94, 0.94, 0.94, 1.0]
        
        im = ax.imshow(rgba, aspect='auto', extent=[0.5, max_doy + 0.5, len(years) - 0.5, -0.5])
        
        for r, y in enumerate(years):
            p_start, p_end, _ = gs_info[y]
            y_bot = r + 0.5
            y_top = r - 0.5
            ax.plot([p_start - 0.5, p_start - 0.5], [y_top, y_bot], color='#D32F2F', linewidth=1.5, linestyle='--')
            ax.plot([p_end + 0.5, p_end + 0.5], [y_top, y_bot], color='#D32F2F', linewidth=1.5, linestyle='--')
            
        # Y-axis ticks & labels: only on leftmost panel
        if ax == axes[0]:
            ax.set_yticks([0, 1])
            ax.set_yticklabels(year_labels, fontsize=9.5, fontweight='bold')
            for tick_label, color in zip(ax.get_yticklabels(), y_colors):
                tick_label.set_color(color)
        else:
            ax.set_yticks([])
            
        ax.set_xticks(month_starts)
        ax.set_xticklabels(month_names, fontsize=8.5)
        ax.set_xlabel('Month', fontsize=9.5, fontweight='bold', labelpad=4)
        ax.set_title(label, fontsize=10.5, fontweight='bold', pad=32)
        
        # Colorbar
        cax = ax.inset_axes([0.15, 1.07, 0.70, 0.055])
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
        cb = fig.colorbar(sm, cax=cax, orientation='horizontal')
        cb.set_ticks(ticks)
        cb.ax.tick_params(labelsize=7.5, pad=1.5)
        cb.outline.set_linewidth(0.4)
        
    fig.suptitle('Daily High-Resolution Agroclimatic Heat-Stripes (25SP vs 26SP)',
                 fontsize=13, fontweight='bold', y=1.02)
    plt.tight_layout()
    plt.savefig(out_path, bbox_inches='tight', dpi=dpi)
    pdf_path = str(out_path).replace('.png', '.pdf')
    svg_path = str(out_path).replace('.png', '.svg')
    plt.savefig(pdf_path, bbox_inches='tight')
    plt.savefig(svg_path, bbox_inches='tight')
    plt.close()
    print(f"Daily plot saved to: {out_path} (and .pdf/.svg)")


def plot_comprehensive_dashboard(df, gs_info, out_path, dpi=600):
    """
    Generate a publication-grade multi-panel comparative figure:
    Top Row: Dekad Heatmaps (TMAX, TMIN, SRAD)
    Bottom Row: Daily Dynamic Differences & Accumulated Growing Season Statistics.
    """
    colormaps = get_reference_colormaps()
    vars_to_plot = ['TMAX', 'TMIN', 'SRAD']
    
    n_dekads = 21
    dekad_range = list(range(1, n_dekads + 1))
    dekad_df = df[df['DEKAD_ID'] <= n_dekads].groupby(['YEAR', 'DEKAD_ID'])[vars_to_plot].mean().reset_index()
    
    years = [2026, 2025]
    year_labels = ['26SP (2026)', '25SP (2025)']
    y_colors = ['#C0392B', '#2980B9']
    
    gs_dekads = {}
    for y, (p_doy, h_doy, first_h_doy) in gs_info.items():
        p_dt = pd.to_datetime(f"{y}{p_doy:03d}", format='%Y%j')
        h_dt = pd.to_datetime(f"{y}{h_doy:03d}", format='%Y%j')
        p_dekad = (p_dt.month - 1) * 3 + (1 if p_dt.day <= 10 else (2 if p_dt.day <= 20 else 3))
        h_dekad = (h_dt.month - 1) * 3 + (1 if h_dt.day <= 10 else (2 if h_dt.day <= 20 else 3))
        gs_dekads[y] = (p_dekad, h_dekad)
        
    fig = plt.figure(figsize=(15.5, 8.8), dpi=dpi)
    gs_grid = fig.add_gridspec(2, 3, height_ratios=[1.0, 1.15], hspace=0.42, wspace=0.22)
    
    month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul']
    month_mid_dekads = [1.5, 4.5, 7.5, 10.5, 13.5, 16.5, 19.5]
    
    # Top Row: Dekad Heatmaps
    for c_ax, var_name in enumerate(vars_to_plot):
        ax = fig.add_subplot(gs_grid[0, c_ax])
        cmap, norm, ticks, label = colormaps[var_name]
        
        mat = np.full((len(years), n_dekads), np.nan)
        is_gs = np.full((len(years), n_dekads), False)
        
        for r, y in enumerate(years):
            sub = dekad_df[dekad_df['YEAR'] == y].set_index('DEKAD_ID')
            p_dek, h_dek = gs_dekads[y]
            for c, d in enumerate(dekad_range):
                if d in sub.index:
                    mat[r, c] = sub.loc[d, var_name]
                    if p_dek <= d <= h_dek:
                        is_gs[r, c] = True
                        
        rgba = cmap(norm(mat))
        gray_rgba = to_grayscale(rgba)
        
        mask = (~is_gs) & (~np.isnan(mat))
        for i in range(3):
            rgba[..., i] = np.where(mask, gray_rgba[..., i], rgba[..., i])
            
        for r in range(len(years)):
            for c in range(n_dekads):
                color = (0.95, 0.95, 0.95, 1.0) if np.isnan(mat[r, c]) else rgba[r, c]
                rect = Rectangle((c, r), 1, 1, facecolor=color, edgecolor='#333333', linewidth=0.5)
                ax.add_patch(rect)
                
        for r, y in enumerate(years):
            p_dek, h_dek = gs_dekads[y]
            ax.plot([p_dek - 1, p_dek - 1], [r, r + 1], color='#D32F2F', linewidth=1.5, linestyle='--')
            ax.plot([h_dek, h_dek], [r, r + 1], color='#D32F2F', linewidth=1.5, linestyle='--')
            
        ax.set_xlim(0, n_dekads)
        ax.set_ylim(len(years), 0)
        
        if c_ax == 0:
            ax.set_yticks([0.5, 1.5])
            ax.set_yticklabels(year_labels, fontsize=9.5, fontweight='bold')
            for tick_label, color in zip(ax.get_yticklabels(), y_colors):
                tick_label.set_color(color)
        else:
            ax.set_yticks([])
            
        ax.set_xticks(month_mid_dekads)
        ax.set_xticklabels(month_names, fontsize=8.5)
        ax.set_xticks(range(n_dekads + 1), minor=True)
        ax.tick_params(which='minor', length=2.5, color='#777777')
        ax.tick_params(which='major', length=0)
        ax.set_xlabel('Month', fontsize=9, fontweight='bold', labelpad=2)
        ax.set_title(f"({chr(97 + c_ax)}) {label}", fontsize=10.5, fontweight='bold', pad=32)
        
        cax = ax.inset_axes([0.15, 1.07, 0.70, 0.055])
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
        cb = fig.colorbar(sm, cax=cax, orientation='horizontal')
        cb.set_ticks(ticks)
        cb.ax.tick_params(labelsize=7.5, pad=1.5)
        cb.outline.set_linewidth(0.4)

    # Bottom Row: Daily Difference Curves during Growing Season
    doy_common = np.arange(75, 193)
    dap_axis = doy_common - 75
    
    d25 = df[df['YEAR'] == 2025].set_index('DOY').loc[doy_common]
    d26 = df[df['YEAR'] == 2026].set_index('DOY').loc[doy_common]
    
    diff_configs = [
        ('TMAX', 'Δ Daily Max Temp. (26SP - 25SP)', '#E65100', '°C'),
        ('TMIN', 'Δ Daily Min Temp. (26SP - 25SP)', '#1565C0', '°C'),
        ('SRAD', 'Δ Daily Solar Rad. (26SP - 25SP)', '#C99700', 'MJ/m²·d')
    ]
    
    for c_ax, (var_name, title_str, line_color, unit_str) in enumerate(diff_configs):
        ax = fig.add_subplot(gs_grid[1, c_ax])
        diff_vals = d26[var_name].values - d25[var_name].values
        smooth_vals = pd.Series(diff_vals).rolling(7, center=True, min_periods=1).mean().values
        
        ax.bar(dap_axis, diff_vals, width=0.8, color=line_color, alpha=0.35, label='Daily Δ')
        ax.plot(dap_axis, smooth_vals, color=line_color, linewidth=2.0, label='7-day trend')
        ax.axhline(0, color='black', linestyle='-', linewidth=0.8, alpha=0.7)
        
        mean_diff = np.mean(diff_vals)
        ax.axhline(mean_diff, color='#B71C1C', linestyle=':', linewidth=1.4,
                   label=f'Mean Δ: {mean_diff:+.2f} {unit_str}')
                   
        ax.set_title(f"({chr(100 + c_ax)}) {title_str}", fontsize=9.8, fontweight='bold', pad=10)
        ax.set_xlabel('Days After Planting (DAP, from Mar 16)', fontsize=9, fontweight='bold')
        ax.set_ylabel(f'Difference ({unit_str})', fontsize=8.5)
        ax.grid(True, linestyle='--', alpha=0.3)
        ax.legend(loc='upper right', fontsize=7.5, framealpha=0.9)
                
    fig.suptitle('Two-Season Agrometeorological Dynamics & Phenological Contrast (25SP vs 26SP)',
                 fontsize=13.5, fontweight='bold', y=0.99)
                 
    plt.savefig(out_path, bbox_inches='tight', dpi=dpi)
    pdf_path = str(out_path).replace('.png', '.pdf')
    svg_path = str(out_path).replace('.png', '.svg')
    plt.savefig(pdf_path, bbox_inches='tight')
    plt.savefig(svg_path, bbox_inches='tight')
    plt.close()
    print(f"Comprehensive dashboard saved to: {out_path} (and .pdf/.svg)")


def plot_daily_dashboard(df, gs_info, out_path, max_doy=205, dpi=600):
    """
    Generate publication-grade multi-panel comparative figure:
    Top Row: Daily High-Resolution Heatmaps (TMAX, TMIN, SRAD) with grayscale for non-growing season.
    Bottom Row: Daily Dynamic Differences & Accumulated Growing Season Statistics.
    """
    colormaps = get_reference_colormaps()
    vars_to_plot = ['TMAX', 'TMIN', 'SRAD']
    
    doy_range = np.arange(1, max_doy + 1)
    years = [2026, 2025]
    year_labels = ['26SP (2026)', '25SP (2025)']
    y_colors = ['#C0392B', '#2980B9']
    
    fig = plt.figure(figsize=(15.5, 8.8), dpi=dpi)
    gs_grid = fig.add_gridspec(2, 3, height_ratios=[1.0, 1.15], hspace=0.42, wspace=0.22)
    
    month_starts = [1, 32, 60, 91, 121, 152, 182]
    month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul']
    
    # Top Row: Daily Heatmaps
    for c_ax, var_name in enumerate(vars_to_plot):
        ax = fig.add_subplot(gs_grid[0, c_ax])
        cmap, norm, ticks, label = colormaps[var_name]
        
        mat = np.full((len(years), len(doy_range)), np.nan)
        is_gs = np.full((len(years), len(doy_range)), False)
        
        for r, y in enumerate(years):
            sub = df[df['YEAR'] == y].set_index('DOY')
            p_start, p_end, _ = gs_info[y]
            for c, doy in enumerate(doy_range):
                if doy in sub.index:
                    mat[r, c] = sub.loc[doy, var_name]
                    if p_start <= doy <= p_end:
                        is_gs[r, c] = True
                        
        rgba = cmap(norm(mat))
        gray_rgba = to_grayscale(rgba)
        
        mask = (~is_gs) & (~np.isnan(mat))
        for i in range(3):
            rgba[..., i] = np.where(mask, gray_rgba[..., i], rgba[..., i])
        rgba[np.isnan(mat)] = [0.94, 0.94, 0.94, 1.0]
        
        im = ax.imshow(rgba, aspect='auto', extent=[0.5, max_doy + 0.5, len(years) - 0.5, -0.5])
        
        for r, y in enumerate(years):
            p_start, p_end, _ = gs_info[y]
            y_bot = r + 0.5
            y_top = r - 0.5
            ax.plot([p_start - 0.5, p_start - 0.5], [y_top, y_bot], color='#D32F2F', linewidth=1.5, linestyle='--')
            ax.plot([p_end + 0.5, p_end + 0.5], [y_top, y_bot], color='#D32F2F', linewidth=1.5, linestyle='--')
            
        if c_ax == 0:
            ax.set_yticks([0, 1])
            ax.set_yticklabels(year_labels, fontsize=9.5, fontweight='bold')
            for tick_label, color in zip(ax.get_yticklabels(), y_colors):
                tick_label.set_color(color)
        else:
            ax.set_yticks([])
            
        ax.set_xticks(month_starts)
        ax.set_xticklabels(month_names, fontsize=8.5)
        ax.set_xlabel('Month', fontsize=9, fontweight='bold', labelpad=2)
        ax.set_title(f"({chr(97 + c_ax)}) {label}", fontsize=10.5, fontweight='bold', pad=32)
        
        cax = ax.inset_axes([0.15, 1.07, 0.70, 0.055])
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
        cb = fig.colorbar(sm, cax=cax, orientation='horizontal')
        cb.set_ticks(ticks)
        cb.ax.tick_params(labelsize=7.5, pad=1.5)
        cb.outline.set_linewidth(0.4)

    # Bottom Row: Daily Difference Curves during Growing Season
    doy_common = np.arange(75, 193)
    dap_axis = doy_common - 75
    
    d25 = df[df['YEAR'] == 2025].set_index('DOY').loc[doy_common]
    d26 = df[df['YEAR'] == 2026].set_index('DOY').loc[doy_common]
    
    diff_configs = [
        ('TMAX', 'Δ Daily Max Temp. (26SP - 25SP)', '#E65100', '°C'),
        ('TMIN', 'Δ Daily Min Temp. (26SP - 25SP)', '#1565C0', '°C'),
        ('SRAD', 'Δ Daily Solar Rad. (26SP - 25SP)', '#C99700', 'MJ/m²·d')
    ]
    
    for c_ax, (var_name, title_str, line_color, unit_str) in enumerate(diff_configs):
        ax = fig.add_subplot(gs_grid[1, c_ax])
        diff_vals = d26[var_name].values - d25[var_name].values
        smooth_vals = pd.Series(diff_vals).rolling(7, center=True, min_periods=1).mean().values
        
        ax.bar(dap_axis, diff_vals, width=0.8, color=line_color, alpha=0.35, label='Daily Δ')
        ax.plot(dap_axis, smooth_vals, color=line_color, linewidth=2.0, label='7-day trend')
        ax.axhline(0, color='black', linestyle='-', linewidth=0.8, alpha=0.7)
        
        mean_diff = np.mean(diff_vals)
        ax.axhline(mean_diff, color='#B71C1C', linestyle=':', linewidth=1.4,
                   label=f'Mean Δ: {mean_diff:+.2f} {unit_str}')
                   
        ax.set_title(f"({chr(100 + c_ax)}) {title_str}", fontsize=9.8, fontweight='bold', pad=10)
        ax.set_xlabel('Days After Planting (DAP, from Mar 16)', fontsize=9, fontweight='bold')
        ax.set_ylabel(f'Difference ({unit_str})', fontsize=8.5)
        ax.grid(True, linestyle='--', alpha=0.3)
        ax.legend(loc='upper right', fontsize=7.5, framealpha=0.9)
                
    fig.suptitle('Two-Season Daily Agrometeorological Dynamics & Phenological Contrast (25SP vs 26SP)',
                 fontsize=13.5, fontweight='bold', y=0.99)
                 
    plt.savefig(out_path, bbox_inches='tight', dpi=dpi)
    pdf_path = str(out_path).replace('.png', '.pdf')
    svg_path = str(out_path).replace('.png', '.svg')
    plt.savefig(pdf_path, bbox_inches='tight')
    plt.savefig(svg_path, bbox_inches='tight')
    plt.close()
    print(f"Daily dashboard saved to: {out_path} (and .pdf/.svg)")


def main():
    parser = argparse.ArgumentParser(description="Plot 25SP vs 26SP weather heatmaps.")
    parser.add_argument('--wth', default='data/user/experiments/XXQL2501/XXLI2502.WTH', help="Path to WTH file")
    parser.add_argument('--tmx25', default='data/user/experiments/XXQL2501/XXQL2501.TMX', help="Path to 25SP TMX")
    parser.add_argument('--tmx26', default='data/user/experiments/XXQL2601/XXQL2601.TMX', help="Path to 26SP TMX")
    parser.add_argument('--out-dir', default='workspace/weather_figures', help="Output directory")
    parser.add_argument('--dpi', type=int, default=600, help="DPI for raster outputs")
    args = parser.parse_args()
    
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    brain_dir = Path("C:/Users/Lidaeus/.gemini/antigravity/brain/8e8f540c-2fbe-412b-8643-2004fc8874d9")
    
    print(f"Loading weather from {args.wth}...")
    df = load_weather_data(args.wth)
    
    print(f"Parsing 25SP phenology from {args.tmx25}...")
    p25, h25, fh25 = parse_tmx_dates(args.tmx25)
    p25_doy = p25 % 1000
    h25_doy = h25 % 1000
    fh25_doy = fh25 % 1000 if fh25 else None
    
    print(f"Parsing 26SP phenology from {args.tmx26}...")
    p26, h26, fh26 = parse_tmx_dates(args.tmx26)
    p26_doy = p26 % 1000
    h26_doy = h26 % 1000
    fh26_doy = fh26 % 1000 if fh26 else None
    
    gs_info = {
        2025: (p25_doy, h25_doy, fh25_doy),
        2026: (p26_doy, h26_doy, fh26_doy)
    }
    print(f"25SP Growing season: DOY {p25_doy} to {h25_doy} ({h25_doy - p25_doy + 1} days)")
    print(f"26SP Growing season: DOY {p26_doy} to {h26_doy} ({h26_doy - p26_doy + 1} days)")
    
    # 1. Dekad 3-Panel Heatmap
    p1 = out_dir / 'agrometeorology_dekad_3panel.png'
    plot_dekad_heatmaps(df, gs_info, p1, panel_mode='3panel', dpi=args.dpi)
    if brain_dir.exists():
        import shutil
        shutil.copy(p1, brain_dir / 'agrometeorology_dekad_3panel.png')
        
    # 2. Dekad 6-Panel Heatmap
    p2 = out_dir / 'agrometeorology_dekad_6panel.png'
    plot_dekad_heatmaps(df, gs_info, p2, panel_mode='6panel', dpi=args.dpi)
    if brain_dir.exists():
        import shutil
        shutil.copy(p2, brain_dir / 'agrometeorology_dekad_6panel.png')
        
    # 3. Daily Heat-Stripe
    p3 = out_dir / 'agrometeorology_daily_stripes.png'
    plot_daily_heatmaps(df, gs_info, p3, dpi=args.dpi)
    if brain_dir.exists():
        import shutil
        shutil.copy(p3, brain_dir / 'agrometeorology_daily_stripes.png')
        
    # 4. Comprehensive Dashboard (Dekad on top + Difference curves on bottom) - Retained!
    p4 = out_dir / 'agrometeorology_comprehensive_dashboard.png'
    plot_comprehensive_dashboard(df, gs_info, p4, dpi=args.dpi)
    if brain_dir.exists():
        import shutil
        shutil.copy(p4, brain_dir / 'agrometeorology_comprehensive_dashboard.png')
        
    # 5. Daily Dashboard (Daily Heatmap on top + Difference curves on bottom) - New requested scheme!
    p5 = out_dir / 'agrometeorology_daily_dashboard.png'
    plot_daily_dashboard(df, gs_info, p5, dpi=args.dpi)
    if brain_dir.exists():
        import shutil
        shutil.copy(p5, brain_dir / 'agrometeorology_daily_dashboard.png')
        
    print("\nAll figures generated successfully!")


if __name__ == '__main__':
    main()
