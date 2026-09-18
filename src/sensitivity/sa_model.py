import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import sys

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.sensitivity.output_contract import load_output_contract, observation_names


def _verify_runtime_bundle() -> None:
    """Reject a formal case whose frozen runtime bytes have changed."""
    manifest_path = PROJECT_ROOT / "runtime_manifest.json"
    if not manifest_path.is_file():
        return
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in payload.get("files", []):
        relative = Path(str(item.get("path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"Invalid runtime manifest path: {relative}")
        path = PROJECT_ROOT / relative
        if not path.is_file():
            raise RuntimeError(f"Frozen runtime file is missing: {relative.as_posix()}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != str(item.get("sha256", "")).lower():
            raise RuntimeError(f"Frozen runtime hash mismatch: {relative.as_posix()}")


def _workspace_dir_from_this_file():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", ".."))


def _default_observation_names():
    return observation_names(load_output_contract())


def _ensure_base_files(workspace_dir):
    pairs = [
        (os.path.join(workspace_dir, "TMGRO048.ECO"), os.path.join(workspace_dir, "TMGRO048.ECO.base")),
        (os.path.join(workspace_dir, "TMGRO048.SPE"), os.path.join(workspace_dir, "TMGRO048.SPE.base")),
    ]
    for src, dst in pairs:
        if os.path.exists(dst):
            continue
        if os.path.exists(src):
            shutil.copy(src, dst)


def _read_param_csv_as_dict(param_csv_path):
    if not param_csv_path or not os.path.exists(param_csv_path):
        return {}
    with open(param_csv_path, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return {}
    header = [c.strip() for c in rows[0]]
    if len(header) >= 2 and header[0].lower() in {"name", "parameter", "parnme"}:
        name_idx = 0
        val_idx = 1
    else:
        name_idx = 0
        val_idx = 1 if len(header) > 1 else None
    out = {}
    for r in rows[1:]:
        if val_idx is None or len(r) <= val_idx:
            continue
        k = str(r[name_idx]).strip().upper()
        if not k:
            continue
        try:
            v = float(str(r[val_idx]).strip())
        except Exception:
            continue
        out[k] = v
    return out


def _parse_evaluate_out(evaluate_path):
    if not evaluate_path or not os.path.exists(evaluate_path):
        return []
    header = None
    rows = []
    with open(evaluate_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("@RUN"):
                header = line.strip().split()
                continue
            if not header:
                continue
            if not line.strip() or line.startswith("*") or line.startswith("!") or line.startswith("@"):
                continue
            parts = line.strip().split()
            if len(parts) < len(header):
                parts += ["-99"] * (len(header) - len(parts))
            rows.append(dict(zip(header, parts[: len(header)])))
    return rows


def _parse_soilpbal_by_run(path):
    if not path or not os.path.exists(path):
        return {}
    by_run = {}
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        header = None
        for line in f:
            line_str = line.strip()
            if line_str.startswith("@Run") or line_str.startswith("@RUN"):
                header = line_str.split()
                continue
            if not header or not line_str or line_str.startswith("*") or line_str.startswith("!"):
                continue
            parts = line_str.split()
            if len(parts) < len(header):
                continue
            if "INIT" in parts:
                continue
            try:
                run_no = int(parts[0])
            except Exception:
                continue
            row = {}
            for col_name, val_str in zip(header, parts):
                try:
                    row[col_name.upper()] = float(val_str)
                except Exception:
                    row[col_name.upper()] = val_str
            by_run[run_no] = row
    return by_run


def _parse_dssat_out_by_run(path, need_cols):
    if not path or not os.path.exists(path):
        return {}
    need_cols = [c for c in (need_cols or []) if c]
    if not need_cols:
        return {}

    by_run = {}
    current_run = None
    header = None
    idx = {}

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("*RUN"):
                m = re.match(r"^\*RUN\s+(\d+)", line)
                current_run = int(m.group(1)) if m else None
                header = None
                idx = {}
                continue
            if line.startswith(("@YEAR", "@Run", "@RUN")):
                header = line.strip().split()
                for c in need_cols:
                    try:
                        idx[c] = header.index(c)
                    except ValueError:
                        if c == "PIAVL" and "PAVLD" in header:
                            idx[c] = header.index("PAVLD")
                        elif c == "LEAF_P_END" and "SHPPD" in header:
                            idx[c] = header.index("SHPPD")
                        elif c == "STEM_P_END" and "SHPPD" in header:
                            idx[c] = header.index("SHPPD")
                        elif c == "FRUIT_P_END" and "SDPPD" in header:
                            idx[c] = header.index("SDPPD")
                        elif c == "ROOT_P_END" and "RTPPD" in header:
                            idx[c] = header.index("RTPPD")
                        elif c == "PSTRES1" and "PST1A" in header:
                            idx[c] = header.index("PST1A")
                        elif c == "PSTRES2" and "PST2A" in header:
                            idx[c] = header.index("PST2A")
                        else:
                            idx[c] = None
                continue
            if not header:
                continue
            if (not line.strip()) or line.startswith("*") or line.startswith("!"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            if current_run is None:
                if parts[0].isdigit() and "INIT" not in parts:
                    try:
                        line_run = int(parts[0])
                    except Exception:
                        line_run = None
                    if line_run is not None:
                        row = {"DAP": 0}
                        for c, j in idx.items():
                            if j is None or len(parts) <= j:
                                continue
                            try:
                                row[c] = float(parts[j])
                            except Exception:
                                continue
                        by_run.setdefault(line_run, []).append(row)
                continue
            try:
                dap = int(float(parts[header.index("DAP")])) if "DAP" in header else None
            except Exception:
                dap = None
            if dap is None:
                continue
            row = {"DAP": dap}
            for c, j in idx.items():
                if j is None or len(parts) <= j:
                    continue
                try:
                    val = float(parts[j])
                    if (c == "PSTRES1" and header[j] == "PST1A") or (c == "PSTRES2" and header[j] == "PST2A"):
                        val = 1.0 - val
                    row[c] = val
                except Exception:
                    continue
            by_run.setdefault(current_run, []).append(row)

    for run, series in by_run.items():
        by_run[run] = sorted(series, key=lambda r: r.get("DAP", 0))
    return by_run


def _trapezoid_auc(xs, ys):
    if not xs or not ys or len(xs) != len(ys):
        return None
    if len(xs) < 2:
        return 0.0
    auc = 0.0
    for i in range(1, len(xs)):
        x0, x1 = xs[i - 1], xs[i]
        y0, y1 = ys[i - 1], ys[i]
        auc += 0.5 * (y0 + y1) * (x1 - x0)
    return auc


def _series_value_on_or_before(series, dap, col):
    best = None
    first = None
    for r in series:
        if r.get("DAP") is None:
            continue
        if first is None and col in r:
            first = r[col]
        if r["DAP"] <= dap and col in r:
            best = r[col]
        if r.get("DAP") is not None and r["DAP"] > dap:
            break
    if best is None:
        return first
    return best


def _curve_features(series, col):
    xs = [r["DAP"] for r in series if ("DAP" in r and col in r)]
    ys = [r[col] for r in series if ("DAP" in r and col in r)]
    if not xs:
        return {}
    peak = max(ys)
    t_peak = xs[ys.index(peak)]
    end = ys[-1]
    auc = _trapezoid_auc(xs, ys)
    return {"peak": peak, "t_peak": t_peak, "end": end, "auc": auc}


def _cumulative_dap_fraction(series, col, fraction=0.5):
    """Return the first interpolated DAP reaching a fraction of final cumulative yield.

    DAP50 is computed only by linear trans-interpolation between the original
    DSSAT cumulative nodes — never from an R smoothing curve. A cumulative
    harvest series must be non-decreasing and end positive; a decreasing node,
    a non-positive final value, or an empty/missing series marks the response
    as not estimable (``None``), which the caller emits as the DSSAT ``-99``
    missing sentinel so the response audit flags it. The series is never
    silently patched.
    """

    points = [
        (float(row["DAP"]), float(row[col]))
        for row in series
        if "DAP" in row and col in row and float(row[col]) >= 0.0
    ]
    if not points or points[-1][1] <= 0.0:
        return None
    # A cumulative series must be non-decreasing at every node: the physical
    # quantity (cumulative dry fruit mass) cannot drop, so any decrease signals
    # an extraction/ordering error rather than a real trajectory. Verify the
    # whole series up front so a late decrease still rejects the response.
    for (_, current), (_, following) in zip(points, points[1:]):
        if following < current:
            return None
    target = float(fraction) * points[-1][1]
    previous_dap, previous_value = points[0]
    if previous_value >= target:
        return previous_dap
    for dap, value in points[1:]:
        if value >= target:
            share = (target - previous_value) / (value - previous_value)
            return previous_dap + share * (dap - previous_dap)
        previous_dap, previous_value = dap, value
    return points[-1][0]


def _linear_slope(points):
    """Return the ordinary least-squares slope for paired finite points."""

    valid = [(float(x), float(y)) for x, y in points if y is not None and float(y) != -99.0]
    if len(valid) < 2:
        return None
    x_mean = sum(x for x, _ in valid) / len(valid)
    y_mean = sum(y for _, y in valid) / len(valid)
    denominator = sum((x - x_mean) ** 2 for x, _ in valid)
    if denominator <= 0.0:
        return None
    return sum((x - x_mean) * (y - y_mean) for x, y in valid) / denominator


def derive_water_nitrogen_responses(values, contract):
    """Derive paired water effects, N-response slopes and their interaction."""

    design = contract.get("water_nitrogen_design")
    if not isinstance(design, dict):
        return {}
    derived = {}
    for feature in design["contrast_features"]:
        for level, pair in design["water_pairs"].items():
            high = values.get(f"TN{int(pair[0])}_{feature}")
            low = values.get(f"TN{int(pair[1])}_{feature}")
            if high is not None and low is not None and high != -99.0 and low != -99.0:
                derived[f"WN_WATER_{str(level).upper()}_{feature}"] = float(high) - float(low)

        slopes = {}
        for water in ("W3", "W1"):
            points = [
                (
                    float(row["n_kg_ha"]),
                    values.get(f"TN{int(row['treatment'])}_{feature}"),
                )
                for row in design["nitrogen_series"][water]
            ]
            slope = _linear_slope(points)
            if slope is not None:
                slopes[water] = slope
                derived[f"WN_NSLOPE_{water}_{feature}"] = slope
        if set(slopes) == {"W3", "W1"}:
            derived[f"WN_INTERACTION_{feature}"] = slopes["W3"] - slopes["W1"]
    return derived


def _as_float(v, default=-99.0):
    try:
        return float(v)
    except Exception:
        return float(default)


def _wait_for_file(path, timeout_s=2.0, poll_s=0.05):
    if not path:
        return False
    t0 = time.time()
    while (time.time() - t0) <= float(timeout_s):
        if os.path.exists(path):
            return True
        time.sleep(float(poll_s))
    return os.path.exists(path)


def compute_indicators(
    workspace_dir,
    batch_path,
    cultivar,
    param_csv_path,
    out_path,
    time_points=None,
    obs_order_path=None,
    input_dir=None,
    failure_artifact_dir=None,
    output_profile=None,
):
    _ensure_base_files(workspace_dir)

    workspace_dir = os.path.abspath(workspace_dir)
    if not os.path.isabs(out_path):
        out_path = os.path.abspath(os.path.join(workspace_dir, out_path))
    else:
        out_path = os.path.abspath(out_path)

    if not os.path.isabs(param_csv_path):
        param_csv_path = os.path.abspath(os.path.join(workspace_dir, param_csv_path))
    else:
        param_csv_path = os.path.abspath(param_csv_path)

    if not os.path.isabs(batch_path):
        batch_path = os.path.abspath(os.path.join(workspace_dir, batch_path))
    else:
        batch_path = os.path.abspath(batch_path)

    if obs_order_path:
        if not os.path.isabs(obs_order_path):
            obs_order_path = os.path.abspath(os.path.join(workspace_dir, obs_order_path))
        else:
            obs_order_path = os.path.abspath(obs_order_path)

    ordered_names = None
    if obs_order_path and os.path.exists(obs_order_path):
        with open(obs_order_path, "r", encoding="utf-8", errors="ignore") as f:
            ordered_names = [ln.strip() for ln in f.readlines() if ln.strip()]
    contract = load_output_contract(output_profile) if output_profile else load_output_contract()
    if not ordered_names:
        ordered_names = observation_names(contract)

    def _write_out(values):
        os.makedirs(os.path.dirname(out_path), exist_ok=True) if os.path.dirname(out_path) else None
        out_dir = os.path.dirname(out_path) or workspace_dir
        fd, tmp_path = tempfile.mkstemp(prefix=os.path.basename(out_path) + ".", suffix=".tmp", dir=out_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for name in ordered_names:
                    v = values.get(name, -99.0) if values else -99.0
                    f.write(f" {float(v):.6f} \n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, out_path)
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

    run_root = os.path.join(workspace_dir, "_sa_tmp_runs")
    os.makedirs(run_root, exist_ok=True)
    run_dir = tempfile.mkdtemp(prefix="run_", dir=run_root)

    try:
        if not os.path.exists(param_csv_path):
            _wait_for_file(param_csv_path, timeout_s=3.0, poll_s=0.05)
        if not os.path.exists(param_csv_path):
            _write_out({})
            return

        param_snapshot = os.path.join(run_dir, "sa_params.snapshot.csv")
        try:
            shutil.copy(param_csv_path, param_snapshot)
        except FileNotFoundError:
            _wait_for_file(param_csv_path, timeout_s=3.0, poll_s=0.05)
            if not os.path.exists(param_csv_path):
                _write_out({})
                return
            shutil.copy(param_csv_path, param_snapshot)

        # Stage input bundle files (FileX, Weather, Soil, Genotype, Batch) into ephemeral run_dir
        staging_dir = input_dir
        if not staging_dir or not os.path.isdir(staging_dir):
            cand = os.path.dirname(os.path.abspath(batch_path))
            if cand and os.path.isdir(cand) and any(f.endswith(".TMX") for f in os.listdir(cand)):
                staging_dir = cand
        if staging_dir and os.path.isdir(staging_dir):
            for item in os.listdir(staging_dir):
                s = os.path.join(staging_dir, item)
                d = os.path.join(run_dir, item)
                if os.path.isfile(s):
                    shutil.copy2(s, d)

        active_batch_path = os.path.join(run_dir, os.path.basename(batch_path))
        if not os.path.exists(active_batch_path):
            active_batch_path = batch_path

        local_dssatpro = os.path.join(run_dir, "DSSATPRO.v48")
        if not os.path.exists(local_dssatpro):
            for cand_pro in [
                PROJECT_ROOT / "data" / "templates" / "DSSATPRO.v48",
                PROJECT_ROOT / "DSSATPRO.v48",
            ]:
                if cand_pro.is_file():
                    shutil.copy2(str(cand_pro), local_dssatpro)
                    break

        local_exe = os.path.join(run_dir, "DSCSM048.EXE")
        if not os.path.exists(local_exe):
            for cand_exe in [
                PROJECT_ROOT / "workspace" / "DSCSM048.EXE",
                PROJECT_ROOT / "DSCSM048.EXE",
                Path(r"C:\DSSAT48\DSCSM048.EXE"),
            ]:
                if cand_exe.is_file():
                    shutil.copy2(str(cand_exe), local_exe)
                    break

        run_dssat_path = str(PROJECT_ROOT / "src" / "dssat" / "run_dssat.py")
        if not os.path.exists(run_dssat_path):
            run_dssat_path = str(PROJECT_ROOT / "src" / "calibration" / "run_dssat.py")
        if not os.path.exists(run_dssat_path):
            raise FileNotFoundError(f"DSSAT runner entry point not found: {run_dssat_path}")
        cmd = [
            "python",
            run_dssat_path,
            "--param-csv",
            param_snapshot,
            "--batch",
            active_batch_path,
            "--cultivar",
            cultivar,
            "--harvest-var",
            "CHPDT",
        ]
        if any(str(feature).upper() in {"LEAF_N_END", "STEM_N_END", "ROOT_N_END", "FRUIT_N_END"}
               for feature in contract.get("features", [])):
            cmd.append("--keep-nitrogen-outputs")
        p_features = {
            "LEAF_P_END", "STEM_P_END", "ROOT_P_END", "FRUIT_P_END",
            "PSTRES1", "PSTRES2", "PSTRAT", "SEASBAL", "PIAVL", "PAVLD", "PUPC",
        }
        if any(str(feature).upper() in p_features for feature in contract.get("features", [])):
            cmd.append("--keep-phosphorus-outputs")

        sub_env = os.environ.copy()
        sub_env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, cwd=run_dir, env=sub_env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        dssat_ok = proc.returncode == 0
        if not dssat_ok:
            print(f"RUNNER_ADVISORY DSSAT sensitivity run failed with exit code {proc.returncode}", file=sys.stderr, flush=True)
            _write_out({})
            return

        eval_rows = _parse_evaluate_out(os.path.join(run_dir, "Evaluate.OUT")) if dssat_ok else []
        plantgro = (
            _parse_dssat_out_by_run(os.path.join(run_dir, "PlantGro.OUT"), ["LAID", "LWAD", "SWAD", "CWAD", "HIAD"]) if dssat_ok else {}
        )
        freshwt = _parse_dssat_out_by_run(os.path.join(run_dir, "FreshWt.OUT"), ["CHPDT", "CHFPW", "PDMCD"]) if dssat_ok else {}
        plantn = _parse_dssat_out_by_run(
            os.path.join(run_dir, "PlantN.OUT"),
            ["LN%D", "SN%D", "RN%D", "FRN%D", "CNAD", "GNAD", "VNAD"],
        ) if dssat_ok else {}
        plantp = (
            _parse_dssat_out_by_run(
                os.path.join(run_dir, "PlantP.OUT"),
                ["SHPPD", "SDPPD", "RTPPD", "PLPPD", "PST1A", "PST2A", "PSTRAT", "PUPD", "PUPC", "LP%D", "SP%D", "FRP%D"],
            ) if dssat_ok else {}
        )
        soilpi = (
            _parse_dssat_out_by_run(
                os.path.join(run_dir, "SoilPi.OUT"),
                ["PAVLD", "PIAVL", "PIAD", "PSOLD", "PLABD", "PUPC"],
            ) if dssat_ok else {}
        )
        soilpbal = (
            _parse_soilpbal_by_run(os.path.join(run_dir, "SoilPBalSum.OUT")) if dssat_ok else {}
        )

        run_to_tn = {}
        for r in eval_rows:
            try:
                run_no = int(float(r.get("@RUN") or r.get("RUN") or r.get("RUNNO") or r.get("RUN#") or r.get("RUN#")))
            except Exception:
                try:
                    run_no = int(float(r.get("RUN", -99)))
                except Exception:
                    continue
            try:
                tn = int(float(r.get("TN", -99)))
            except Exception:
                tn = -99
            run_to_tn[run_no] = tn

        lai_time_points = list(contract["lai_time_points"])
        fruit_time_points = list(contract["fruit_time_points"])
        if time_points is not None:
            lai_time_points = list(time_points)
            fruit_time_points = list(time_points)
        values = {}

        def _emit(name, val):
            values[str(name)] = _as_float(val)

        for r in eval_rows:
            run_no = None
            for k in ["RUN", "@RUN"]:
                if k in r:
                    try:
                        run_no = int(float(r[k]))
                    except Exception:
                        run_no = None
            if run_no is None:
                continue
            tn = run_to_tn.get(run_no, -99)
            prefix = f"TN{tn}" if tn != -99 else f"RUN{run_no}"

            _emit(f"{prefix}_YIELD_HWAMS", r.get("HWAMS"))
            _emit(f"{prefix}_HIAMS", r.get("HIAMS"))
            # DSSAT Evaluate.OUT suffixes M/S mean measured/simulated.  SA must
            # expose the simulated maximum LAI, never the FileA measured value.
            _emit(f"{prefix}_LAIXS", r.get("LAIXS"))
            _emit(f"{prefix}_CWAMS", r.get("CWAMS"))
            _emit(f"{prefix}_ADAPS", r.get("ADAPS"))
            _emit(f"{prefix}_PDFPS", r.get("PDFPS"))
            _emit(f"{prefix}_MDAPS", r.get("MDAPS"))

            pg = plantgro.get(run_no, [])
            fw = freshwt.get(run_no, [])
            pn = plantn.get(run_no, [])
            pp = plantp.get(run_no, [])
            spi = soilpi.get(run_no, [])

            lai = _curve_features(pg, "LAID")
            fruit = _curve_features(fw, "CHPDT")

            _emit(f"{prefix}_LAI_AUC", lai.get("auc"))
            _emit(f"{prefix}_LAI_PEAK", lai.get("peak"))
            _emit(f"{prefix}_LAI_TPEAK", lai.get("t_peak"))
            _emit(f"{prefix}_LAI_END", lai.get("end"))

            _emit(f"{prefix}_FRUITD_AUC", fruit.get("auc"))
            _emit(f"{prefix}_FRUITD_END", fruit.get("end"))
            _emit(f"{prefix}_CUMHARVEST_DAP50", _cumulative_dap_fraction(fw, "CHPDT", 0.5))

            # Fruit water content: PDMCD is DSSAT's dynamic dry-matter
            # concentration (fraction), so water content = 1 - PDMCD.
            # Also derive from CHPDT/CHFPW as an independent cross-check.
            fwc_curve = _curve_features(fw, "PDMCD")
            pdmcd_end = fwc_curve.get("end")
            _emit(f"{prefix}_FWC_END", (1.0 - pdmcd_end) if pdmcd_end is not None else None)
            pdmcd_peak = fwc_curve.get("peak")
            pdmcd_min = min((row["PDMCD"] for row in fw if "PDMCD" in row), default=None)
            _emit(f"{prefix}_FWC_PEAK", (1.0 - pdmcd_min) if pdmcd_min is not None else None)
            _emit(f"{prefix}_PDMCD_END", pdmcd_end)
            _emit(f"{prefix}_PDMCD_PEAK", pdmcd_peak)
            # Cross-check: water content from CHPDT/CHFPW at harvest.
            chfpw_curve = _curve_features(fw, "CHFPW")
            chfpw_end = chfpw_curve.get("end")
            chpdt_end = fruit.get("end")
            if chfpw_end is not None and chpdt_end is not None and chfpw_end > 0:
                _emit(f"{prefix}_FWC_FROM_RATIO_END", 1.0 - chpdt_end / chfpw_end)
            else:
                _emit(f"{prefix}_FWC_FROM_RATIO_END", None)

            if pg:
                last = pg[-1]
                _emit(f"{prefix}_LEAF_END_LWAD", last.get("LWAD"))
                _emit(f"{prefix}_STEM_END_SWAD", last.get("SWAD"))
                _emit(f"{prefix}_AGB_END_CWAD", last.get("CWAD"))
                _emit(f"{prefix}_HI_END_HIAD", last.get("HIAD"))

            if pn:
                # PlantN.OUT is the organ-N response source.  CNAD/GNAD/VNAD
                # are retained only as diagnostics; shell is never inferred
                # from whole-fruit nitrogen. FRN%D is whole-fruit N
                # concentration and is deliberately labelled as such.
                last_n = pn[-1]
                _emit(f"{prefix}_LEAF_N_END", last_n.get("LN%D"))
                _emit(f"{prefix}_STEM_N_END", last_n.get("SN%D"))
                _emit(f"{prefix}_ROOT_N_END", last_n.get("RN%D"))
                _emit(f"{prefix}_FRUIT_N_END", last_n.get("FRN%D"))
            if pp:
                last_p = pp[-1]
                shppd = last_p.get("SHPPD")
                _emit(f"{prefix}_LEAF_P_END", last_p.get("LP%D", shppd))
                _emit(f"{prefix}_STEM_P_END", last_p.get("SP%D", shppd))
                _emit(f"{prefix}_ROOT_P_END", last_p.get("RTPPD"))
                _emit(f"{prefix}_FRUIT_P_END", last_p.get("SDPPD", last_p.get("FRP%D")))
                pst1a = last_p.get("PST1A")
                pstres1 = (1.0 - pst1a) if pst1a is not None else last_p.get("PSTRES1")
                _emit(f"{prefix}_PSTRES1", pstres1)
                pst2a = last_p.get("PST2A")
                pstres2 = (1.0 - pst2a) if pst2a is not None else last_p.get("PSTRES2")
                _emit(f"{prefix}_PSTRES2", pstres2)
                _emit(f"{prefix}_PSTRAT", last_p.get("PSTRAT"))
                _emit(f"{prefix}_PUPC", last_p.get("PUPC"))

            if spi:
                last_spi = spi[-1]
                piavl = last_spi.get("PAVLD", last_spi.get("PIAVL"))
                _emit(f"{prefix}_PIAVL", piavl)
                _emit(f"{prefix}_PAVLD", piavl)

            bal_row = soilpbal.get(run_no, {})
            bal_val = bal_row.get("SEASBAL")
            if bal_val is None and spi:
                bal_val = spi[-1].get("SEASBAL")
            _emit(f"{prefix}_SEASBAL", bal_val)

            for tp in lai_time_points:
                _emit(f"{prefix}_LAI_DAP{tp:03d}", _series_value_on_or_before(pg, tp, "LAID"))
            for tp in fruit_time_points:
                _emit(f"{prefix}_FRUITD_DAP{tp:03d}", _series_value_on_or_before(fw, tp, "CHPDT"))

        values.update(derive_water_nitrogen_responses(values, contract))

        group_names = {}
        for name, val in values.items():
            if name.startswith("TN"):
                key = name.split("_", 1)[1]
                group_names.setdefault(key, []).append(val)
        for key, vals in group_names.items():
            if not vals:
                continue
            finite = [v for v in vals if v != -99.0]
            if not finite:
                continue
            _emit(f"MEAN_{key}", sum(finite) / float(len(finite)))

        _write_out(values)
    except Exception as exc:
        if failure_artifact_dir:
            artifact_root = os.path.abspath(failure_artifact_dir)
            os.makedirs(artifact_root, exist_ok=True)
            shutil.copytree(run_dir, os.path.join(artifact_root, "run_files"), dirs_exist_ok=True)
            context = {
                "error_type": type(exc).__name__,
                "error": str(exc),
                "workspace_dir": workspace_dir,
                "batch_path": batch_path,
                "param_csv_path": param_csv_path,
                "input_dir": input_dir,
            }
            with open(os.path.join(artifact_root, "failure_context.json"), "w", encoding="utf-8") as handle:
                json.dump(context, handle, ensure_ascii=False, indent=2)
        raise
    finally:
        keep_all = os.environ.get("DSSAT_KEEP_RUNS", "").strip().lower() in {"1", "true", "yes", "on"}
        if not keep_all:
            try:
                shutil.rmtree(run_dir, ignore_errors=True)
            except Exception:
                pass


def main():
    _verify_runtime_bundle()
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--batch", default=None)
    parser.add_argument("--cultivar", default="TM0008")
    parser.add_argument("--param-csv", default="pest_params.csv")
    parser.add_argument("--out", default="SA_Indicators.OUT")
    parser.add_argument("--obs-order", default=None)
    parser.add_argument("--input-dir", default=None)
    parser.add_argument("--failure-artifact-dir", default=None)
    parser.add_argument("--output-profile", default=None)
    args = parser.parse_args()

    workspace_dir = os.path.normpath(args.workspace) if args.workspace else _workspace_dir_from_this_file()
    batch_path = os.path.normpath(args.batch) if args.batch else os.path.join(workspace_dir, "DSSBatch.v48")
    compute_indicators(
        workspace_dir=workspace_dir,
        batch_path=batch_path,
        cultivar=args.cultivar,
        param_csv_path=args.param_csv,
        out_path=args.out,
        obs_order_path=args.obs_order,
        input_dir=args.input_dir,
        failure_artifact_dir=args.failure_artifact_dir,
        output_profile=args.output_profile,
    )


if __name__ == "__main__":
    main()
