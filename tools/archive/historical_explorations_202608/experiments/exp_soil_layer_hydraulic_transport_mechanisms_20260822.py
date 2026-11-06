"""Detailed Mechanism Testing on Soil Layer Merging, Hydraulic Parameters, and Solute Transport."""
from __future__ import annotations

import re
import sys
from pathlib import Path
import numpy as np
import pandas as pd

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]


def analyze_layer_dispersion_mechanics():
    """Calculates numerical dispersion and solute residence time for 5cm vs 15cm layers."""
    irrigation_event = 20.0 # mm
    sdul = 0.31 # cm3/cm3
    ssat = 0.49 # cm3/cm3
    
    # Layer 1: 0-5cm (thickness 50mm)
    v_ret_5cm = sdul * 50.0 # 15.5 mm
    turnover_5cm = irrigation_event / v_ret_5cm # 1.29 pore volumes
    # In a completely mixed tank, fraction remaining = exp(-turnover)
    rem_5cm = np.exp(-turnover_5cm) * 100
    leached_5cm = 100 - rem_5cm
    
    # Merged Layer 1: 0-15cm (thickness 150mm)
    v_ret_15cm = sdul * 150.0 # 46.5 mm
    turnover_15cm = irrigation_event / v_ret_15cm # 0.43 pore volumes
    rem_15cm = np.exp(-turnover_15cm) * 100
    leached_15cm = 100 - rem_15cm
    
    # Merged Layer 1: 0-20cm (thickness 200mm)
    v_ret_20cm = sdul * 200.0 # 62.0 mm
    turnover_20cm = irrigation_event / v_ret_20cm # 0.32 pore volumes
    rem_20cm = np.exp(-turnover_20cm) * 100
    leached_20cm = 100 - rem_20cm
    
    print("==========================================================================================")
    print("     Hydraulic Dispersion & Solute Flushing Dynamics under 20mm Irrigation Event")
    print("==========================================================================================")
    print(f"1. Thin 0-5 cm Layer (50 mm depth):")
    print(f"   - Capillary Water Storage Capacity: {v_ret_5cm:.1f} mm")
    print(f"   - Single Irrigation Pore Volume Turnover: {turnover_5cm:.2f} PV")
    print(f"   - Solute Retention in Layer: {rem_5cm:.1f}% | Solute Flushed Out to Subsoil: {leached_5cm:.1f}%")
    print(f"\n2. Merged 0-15 cm Layer (150 mm depth):")
    print(f"   - Capillary Water Storage Capacity: {v_ret_15cm:.1f} mm")
    print(f"   - Single Irrigation Pore Volume Turnover: {turnover_15cm:.2f} PV")
    print(f"   - Solute Retention in Layer: {rem_15cm:.1f}% | Solute Flushed Out to Subsoil: {leached_15cm:.1f}%")
    print(f"\n3. Merged 0-20 cm Tillage/Root-Zone Layer (200 mm depth):")
    print(f"   - Capillary Water Storage Capacity: {v_ret_20cm:.1f} mm")
    print(f"   - Single Irrigation Pore Volume Turnover: {turnover_20cm:.2f} PV")
    print(f"   - Solute Retention in Layer: {rem_20cm:.1f}% | Solute Flushed Out to Subsoil: {leached_20cm:.1f}%")


if __name__ == "__main__":
    analyze_layer_dispersion_mechanics()
