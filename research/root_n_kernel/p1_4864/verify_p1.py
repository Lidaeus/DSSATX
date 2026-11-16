import csv

SPECIES = {"1": "UNO3", "2": "UNH4"}


def audit(run_dir, arm, expected_runs):
    trace_rates = {}
    season_end = {}
    soil_totals = {}
    pre_extract = {}
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

    with (run_dir / "LayerRootNUptake.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows and all(len(row) == 25 and None not in row for row in rows)
    matched = set()
    deducted_by_run = {}
    pending_by_run = {}
    pending_rows = 0
    dry_rows = 0
    max_mass_residual = 0.0
    seen = set()
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
        assert abs(settled - deducted - pending) < 1e-10, identity
        assert 0 <= settled <= accepted + 1e-10 and accepted <= candidate + 1e-10, identity
        assert candidate <= cap + 2e-7, identity
        assert int(row["solver_status"]) < 100, identity
        max_mass_residual = max(max_mass_residual, abs(float(row["radial_mass_error_gN_m2"])))
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
    assert len(deducted_by_run) == expected_runs and len(pending_by_run) == expected_runs and max_mass_residual < 1e-9
    soil_residual = max(abs(soil_totals[run] - value) for run, value in deducted_by_run.items())
    # SOILNI's cumulative total uses single precision. The row-by-row check above is tighter.
    assert soil_residual < 0.002, soil_residual
    return {
        "arm": arm,
        "rows": len(rows),
        "matched_soil_rows": len(matched),
        "pending_rows": pending_rows,
        "pending_positive_rows": sum(float(row["pending_gN_m2"]) > 0 for row in rows),
        "dry_rows_theta0_below_LL": dry_rows,
        "max_radial_mass_residual_gN_m2": max_mass_residual,
        "max_soil_cumulative_difference_gN_m2": soil_residual,
        "run_1_deducted_kgN_ha": 10 * deducted_by_run["1"],
        "run_1_pending_kgN_ha": 10 * pending_by_run["1"],
    }

