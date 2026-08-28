from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
p = ROOT / "src/dssat/run_dssat.py"
lines = p.read_text(encoding="utf-8").splitlines()

target_idx = None
for i, l in enumerate(lines):
    if "def _assert_fresh_nonempty" in l:
        target_idx = i
        break

insertion = """def update_planting_details_file(param_csv_path=PARAM_CSV, filex_path=None):
    \"\"\"Inject PLWT (transplant seedling plug biomass) parameter into FileX.\"\"\"
    if not os.path.exists(param_csv_path) or not filex_path or not os.path.exists(filex_path):
        return
    param_dict = _read_param_dict(param_csv_path)
    plwt_val = None
    for k in [\"PLWT\", \"IC_PLWT\", \"PLANT_PLWT\"]:
        if k in param_dict:
            try:
                plwt_val = float(param_dict[k])
                break
            except Exception:
                pass
    if plwt_val is None:
        return

    with open(filex_path, \"r\", encoding=\"utf-8\", errors=\"ignore\") as f:
        lines = f.readlines()

    in_planting = False
    header_cols = []
    plwt_idx = None
    changed = False

    for i, line in enumerate(lines):
        u = line.strip().upper()
        if u.startswith(\"*PLANTING DETAILS\"):
            in_planting = True
        elif in_planting and u.startswith(\"*\"):
            in_planting = False
        elif in_planting and u.startswith(\"@P\"):
            header_cols = [c for c in u.replace(\"@\", \"\").split()]
            if \"PLWT\" in header_cols:
                plwt_idx = header_cols.index(\"PLWT\")
        elif in_planting and plwt_idx is not None and u and not u.startswith(\"@\"):
            parts = line.split()
            if len(parts) > plwt_idx:
                try:
                    p_code = parts[0]
                    pdate = parts[1]
                    edate = parts[2]
                    ppop = float(parts[3])
                    ppoe = float(parts[4])
                    plme = parts[5]
                    plds = parts[6]
                    plrs = parts[7]
                    plrd = parts[8]
                    pldp = parts[9]
                    page = parts[11] if len(parts) > 11 else \"60\"
                    penv = parts[12] if len(parts) > 12 else \"25\"
                    plph = parts[13] if len(parts) > 13 else \"1\"
                    sprl = parts[14] if len(parts) > 14 else \"8\"
                    plname = \"Eggplant\"
                    formatted = f\" {int(p_code):1d} {pdate:5s} {edate:>5s}  {ppop:4.1f}  {ppoe:4.1f}     {plme:1s}     {plds:1s}    {plrs:>2s}    {plrd:>2s}     {pldp:>1s}   {plwt_val:3.1f}    {page:>2s}    {penv:>2s}     {plph:>1s}     {sprl:>1s}                        {plname:s}\\n\"
                    lines[i] = formatted
                    changed = True
                except Exception:
                    pass
    if changed:
        lock_path = os.path.abspath(filex_path) + \".lock\"
        lock_err = _acquire_file_lock(lock_path, timeout_s=180.0, poll_s=0.10, stale_s=900.0)
        if lock_err is not None:
            raise lock_err
        try:
            last_err = _atomic_write_lines(filex_path, lines, n_tries=60, sleep_s=0.20)
            if last_err is not None:
                raise last_err
        finally:
            _release_file_lock(lock_path)
"""

new_lines = lines[:target_idx] + insertion.splitlines() + [""] + lines[target_idx:]
p.write_text("\n".join(new_lines), encoding="utf-8")
print("Successfully inserted update_planting_details_file!")
