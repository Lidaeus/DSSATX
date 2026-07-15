import argparse
import csv
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
            if current_run is None:
                continue
            if line.startswith("@YEAR"):
                header = line.strip().split()
                for c in need_cols:
                    try:
                        idx[c] = header.index(c)
                    except ValueError:
                        idx[c] = None
                continue
            if not header:
                continue
            if (not line.strip()) or line.startswith("*") or line.startswith("!"):
                continue
            parts = line.split()
            if len(parts) < 2:
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
                    row[c] = float(parts[j])
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
    if not ordered_names:
        ordered_names = _default_observation_names()

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

        run_dssat_path = str(PROJECT_ROOT / "src" / "calibration" / "run_dssat.py")
        if not os.path.exists(run_dssat_path):
            raise FileNotFoundError(f"DSSAT calibration entry point not found: {run_dssat_path}")
        cmd = [
            "python",
            run_dssat_path,
            "--param-csv",
            param_snapshot,
            "--batch",
            batch_path,
            "--cultivar",
            cultivar,
            "--harvest-var",
            "CHPDT",
        ]
        if input_dir:
            cmd.extend(["--input-dir", os.path.abspath(input_dir)])
        proc = subprocess.run(cmd, cwd=run_dir, capture_output=True, text=True)
        dssat_ok = proc.returncode == 0
        if not dssat_ok:
            raise RuntimeError(
                f"DSSAT sensitivity run failed with exit code {proc.returncode}\n"
                f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )

        eval_rows = _parse_evaluate_out(os.path.join(run_dir, "Evaluate.OUT")) if dssat_ok else []
        plantgro = (
            _parse_dssat_out_by_run(os.path.join(run_dir, "PlantGro.OUT"), ["LAID", "LWAD", "SWAD", "CWAD", "HIAD"]) if dssat_ok else {}
        )
        freshwt = _parse_dssat_out_by_run(os.path.join(run_dir, "FreshWt.OUT"), ["CHPDT"]) if dssat_ok else {}

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

        time_points = time_points or list(load_output_contract()["time_points"])
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
            _emit(f"{prefix}_LAIXM", r.get("LAIXM"))
            _emit(f"{prefix}_CWAMS", r.get("CWAMS"))
            _emit(f"{prefix}_ADAPS", r.get("ADAPS"))
            _emit(f"{prefix}_PDFPS", r.get("PDFPS"))
            _emit(f"{prefix}_MDAPS", r.get("MDAPS"))

            pg = plantgro.get(run_no, [])
            fw = freshwt.get(run_no, [])

            lai = _curve_features(pg, "LAID")
            fruit = _curve_features(fw, "CHPDT")

            _emit(f"{prefix}_LAI_AUC", lai.get("auc"))
            _emit(f"{prefix}_LAI_PEAK", lai.get("peak"))
            _emit(f"{prefix}_LAI_TPEAK", lai.get("t_peak"))
            _emit(f"{prefix}_LAI_END", lai.get("end"))

            _emit(f"{prefix}_FRUITD_AUC", fruit.get("auc"))
            _emit(f"{prefix}_FRUITD_END", fruit.get("end"))

            if pg:
                last = pg[-1]
                _emit(f"{prefix}_LEAF_END_LWAD", last.get("LWAD"))
                _emit(f"{prefix}_STEM_END_SWAD", last.get("SWAD"))
                _emit(f"{prefix}_AGB_END_CWAD", last.get("CWAD"))
                _emit(f"{prefix}_HI_END_HIAD", last.get("HIAD"))

            for tp in time_points:
                _emit(f"{prefix}_LAI_DAP{tp:03d}", _series_value_on_or_before(pg, tp, "LAID"))
                _emit(f"{prefix}_FRUITD_DAP{tp:03d}", _series_value_on_or_before(fw, tp, "CHPDT"))

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
    finally:
        try:
            shutil.rmtree(run_dir, ignore_errors=True)
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--batch", default=None)
    parser.add_argument("--cultivar", default="TM0008")
    parser.add_argument("--param-csv", default="pest_params.csv")
    parser.add_argument("--out", default="SA_Indicators.OUT")
    parser.add_argument("--obs-order", default=None)
    parser.add_argument("--input-dir", default=None)
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
    )


if __name__ == "__main__":
    main()
