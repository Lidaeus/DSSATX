import csv
import math
from collections import defaultdict

SPECIES = {"1": "UNO3", "2": "UNH4"}


def audit(run_dir, expected_runs):
    trace_rates = {}
    season_end = {}
    soil_totals = {}
    pre_extract = {}
    plant_states = defaultdict(dict)
    raw_carbon_min = math.inf
    with (run_dir / "P0Trace.csv").open(newline="") as stream:
        for row in csv.DictReader(stream):
            run, day, layer, key = (row[k] for k in ("run", "yrdoy", "layer", "key"))
            event = row["event"]
            if event == "rnk_pre_extract":
                pre_extract[run, day, layer, key] = float(row["value"])
            elif event == "soil_debit_before" and key in SPECIES.values():
                trace_rates[run, day, layer, key] = float(row["value"]) / 10
            elif event == "soil_season_end" and key in SPECIES.values():
                season_end[run, layer, key] = float(row["value"]) / 10
            elif event == "soil_season_end" and key == "CNUPTAKE":
                soil_totals[run] = float(row["value"]) / 10
            elif event in ("rnk_plant_settled", "rnk_pool_capacity"):
                if key in ("TRNO3U", "TRNH4U", "TRNU", "PGAVL", "NASSIMD", "RSPNO3", "RSPNH4",
                           "RNO3C", "RNH4C", "QNO3_max", "QNH4_max"):
                    plant_states[run, day][event, key] = float(row["value"])
            elif event == "cg_ledger_end" and key == "PGAVL":
                raw_carbon_min = min(raw_carbon_min, float(row["value"]))

    with (run_dir / "LayerRootNUptake.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows and all(len(row) == 35 and None not in row and None not in row.values() for row in rows)
    assert {(row["transport_mode"], row["shared_transport"]) for row in rows} == {("1", "1")}
    for species in SPECIES:
        assert any(row["species"] == species and float(row["deducted_gN_m2"]) > 0 for row in rows), species
    matched = set()
    deducted_by_run = {}
    pending_by_run = {}
    pending_rows = 0
    dry_rows = 0
    max_steady_residual = 0.0
    seen = set()
    settled_by_day = defaultdict(float)
    for row in rows:
        run, source, commit, layer, species, status = (
            row[key] for key in ("run", "source_day", "soil_commit_day", "layer", "species", "soil_status")
        )
        identity = (run, source, layer, species)
        assert identity not in seen, identity
        seen.add(identity)
        deducted, pending, settled, accepted, candidate, cap = (
            float(row[f"{key}_gN_m2"]) for key in ("deducted", "pending", "settled", "accepted", "candidate", "stock_cap")
        )
        settled_by_day[run, source, species] += settled
        hats, lats = (float(row[f"{name}_candidate_gN_m2"]) for name in ("hats", "lats"))
        assert min(hats, lats) >= 0 and math.isclose(hats + lats, candidate, rel_tol=2e-7, abs_tol=1e-12), identity
        bulk, root, diff = (float(row[key]) for key in ("c_bulk_mgN_L", "c_root_mgN_L", "diffusive_gN_m2"))
        assert 0 <= root <= bulk and diff >= 0, identity
        solver, capped = divmod(int(row["solver_status"]), 10)
        assert solver in (-1, 0, 1, 2) and capped in (0, 1), identity
        residual = float(row["steady_residual_gN_m2"])
        if solver == 2:
            assert abs(residual) < 1e-8, identity
            max_steady_residual = max(max_steady_residual, abs(residual))
        assert 0 <= settled <= accepted + 1e-10 and accepted <= candidate + 1e-10, identity
        assert 0 <= candidate <= cap + 1e-12, identity
        assert abs(settled - deducted - pending) <= 1e-6 * max(1, abs(settled)), identity
        if status == "committed":
            assert int(commit) > int(source) and pending == 0, identity
            trace_key = (run, commit, layer, SPECIES[species])
            assert trace_key not in matched, identity
            assert abs(trace_rates[trace_key] - deducted) < 1e-10, identity
            matched.add(trace_key)
            deducted_by_run[run] = deducted_by_run.get(run, 0.0) + deducted
        else:
            assert status == "pending_season_end" and commit == "0" and deducted == 0, identity
            assert abs(season_end[run, layer, SPECIES[species]] - pending) < 1e-10, identity
            pending_by_run[run] = pending_by_run.get(run, 0.0) + pending
            pending_rows += 1
        theta0 = pre_extract[run, source, layer, "theta0"]
        lower_limit = pre_extract[run, source, layer, "LL"]
        depth = pre_extract[run, source, layer, "DLAYR"]
        water = float(row["rwu_cm_d"])
        assert abs(float(row["theta0"]) - theta0) < 1e-12, identity
        assert abs(float(row["theta_mid"]) - (theta0 - 0.5 * water / depth)) < 1e-12, identity
        if theta0 < lower_limit:
            assert water == 0, identity
            dry_rows += 1
    unmatched = [key for key, value in trace_rates.items() if value > 0 and key not in matched]
    assert not unmatched, unmatched[:5]
    assert len(deducted_by_run) == expected_runs and len(pending_by_run) == expected_runs
    soil_residual = max(abs(soil_totals[run] - value) for run, value in deducted_by_run.items())
    # SOILNI's cumulative total uses single precision. The row-by-row check above is tighter.
    assert soil_residual < 0.002, soil_residual
    budgets = audit_plant(run_dir, plant_states, settled_by_day, deducted_by_run, pending_by_run)
    return {
        **budgets,
        "min_PGAVL_end_of_growth_gCH2O_m2": raw_carbon_min,
        "rows": len(rows),
        "matched_soil_rows": len(matched),
        "pending_rows": pending_rows,
        "pending_positive_rows": sum(float(row["pending_gN_m2"]) > 0 for row in rows),
        "dry_rows_theta0_below_LL": dry_rows,
        "max_steady_residual_gN_m2": max_steady_residual,
        "max_soil_cumulative_difference_gN_m2": soil_residual,
        "run_1_deducted_kgN_ha": 10 * deducted_by_run["1"],
        "run_1_pending_kgN_ha": 10 * pending_by_run["1"],
    }


def audit_plant(run_dir, trace, layer_totals, deducted, pending):
    with (run_dir / "PlantNIntegration.csv").open(newline="") as stream:
        plant = {(r["run"], r["yrdoy"]): r for r in csv.DictReader(stream)}
    n_residual = {}
    carbon_residual = 0.0
    minimum_assim_pg = math.inf
    maximum_pool_fraction = 0.0
    for identity, row in plant.items():
        state = trace[identity]
        u3, u4 = (layer_totals.get((*identity, species), 0.0) for species in SPECIES)
        for species, u, rate in (("NO3", u3, "TRNO3U"), ("NH4", u4, "TRNH4U")):
            assert abs(u - float(row[f"U_{species}"])) < 1e-6, identity
            assert abs(u - state["rnk_plant_settled", rate]) < 1e-6, identity
            stock = float(row[f"Q{species}"])
            capacity = state["rnk_pool_capacity", f"Q{species}_max"]
            assert 0 <= stock <= capacity + 1e-7, identity
            if capacity > 0:
                maximum_pool_fraction = max(maximum_pool_fraction, stock / capacity)
        residual = float(row["Q_residual"])
        assert abs(residual) < 1e-9, identity
        n_residual[identity] = residual
        pg = state["rnk_plant_settled", "PGAVL"]
        assert math.isfinite(pg) and pg >= 0, (identity, "settlement PGAVL", pg)
        minimum_assim_pg = min(minimum_assim_pg, pg)
        assert abs(u3 + u4 - state["rnk_plant_settled", "TRNU"]) < 1e-6, identity
        a3, a4 = (float(row[f"A_{species}"]) for species in ("NO3", "NH4"))
        assert abs(a3 + a4 - state["rnk_plant_settled", "NASSIMD"]) < 1e-6, identity
        cost = (a3 * state["rnk_plant_settled", "RNO3C"] + a4 * state["rnk_plant_settled", "RNH4C"]) / 0.16
        paid = state["rnk_plant_settled", "RSPNO3"] + state["rnk_plant_settled", "RSPNH4"]
        delta = abs(paid - cost)
        assert delta < 1e-5, identity
        carbon_residual = max(carbon_residual, delta)
    cash_days = set()
    max_cash_residual = 0.0
    with (run_dir / "PlantCCash.csv").open(newline="") as stream:
        for row in csv.DictReader(stream):
            identity = (row["run"], row["yrdoy"])
            assert identity not in cash_days, (identity, "duplicate daily cash ledger")
            cash_days.add(identity)
            residual = abs(float(row["CH2O_residual"]))
            assert residual < 1e-5, (identity, "actual carbon cash residual", residual)
            max_cash_residual = max(max_cash_residual, residual)
    assert cash_days == set(plant), "Daily cash and plant nitrogen ledgers cover different days"
    with (run_dir / "PlantABudget.csv").open(newline="") as stream:
        organic = defaultdict(list)
        for row in csv.DictReader(stream):
            organic[row["run"]].append(row)
    assert set(organic) == set(deducted) == set(pending)
    season_residual = 0.0
    for run, rows in organic.items():
        first, last = rows[0], rows[-1]
        day = (run, last["yrdoy"])
        final_q = sum(float(plant[day][name]) for name in ("QNO3", "QNH4"))
        initial_q = 0.0  # NI_RESET initializes both pools to zero.
        offsite = sum(float(last[f"{key}_end"]) - float(first[f"{key}_begin"])
                      for key in ("cumulative_loss", "leak"))
        litter = sum(float(plant[run, row["yrdoy"]]["inorg_litter"]) for row in rows)
        organic_delta = float(last["organic_end_including_seed"]) - float(first["organic_begin_including_seed"])
        residual = organic_delta + final_q - initial_q + offsite + litter - deducted[run] - pending[run]
        assert abs(residual) < 1e-5, (run, residual)
        season_residual = max(season_residual, abs(residual))
    return {
        "max_daily_inorganic_residual_gN_m2": max(map(abs, n_residual.values())),
        "max_season_plant_N_residual_gN_m2": season_residual,
        "max_pool_fraction": maximum_pool_fraction,
        "min_PGAVL_at_settlement_gCH2O_m2": minimum_assim_pg,
        "max_assimilation_cost_difference_gCH2O_m2": carbon_residual,
        "max_daily_cash_residual_gCH2O_m2": max_cash_residual,
    }
