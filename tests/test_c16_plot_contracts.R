# Regression checks for autumn-season attribution and sparse harvest plotting.
if (.Platform$OS.type == "windows") Sys.setlocale("LC_CTYPE", "English_United States.utf8")
source("paper/R/common.R", encoding = "UTF-8")
source("paper/R/fig_selected_dynamics.R", encoding = "UTF-8")

meta <- data.frame(season_id = "25FA", treatment = "1", treatment_label = "TN1",
                   water_level = "W3", nitrogen_level = "N3")
daily <- data.frame(treatment = c("1", "1"), year = c(2025, 2026))
joined <- attach_treatment_metadata(daily, meta, "1")
stopifnot(identical(joined$season_id, c("25FA", "25FA")))
ambiguous <- rbind(meta, transform(meta, season_id = "25SP"))
stopifnot(inherits(try(attach_treatment_metadata(daily, ambiguous, "1"), silent = TRUE), "try-error"))

events <- data.frame(variable = "FRESH_CUM", treatment = "1", season_id = "25FA",
                     time = c(100, 120, 140), simulated = c(5, 10, 15))
curve <- monotone_cumulative_curve(events)
stopifnot(nrow(curve) >= 240L, all(diff(curve$simulated) >= -1e-10),
          abs(curve$simulated[[1]] - 5) < 1e-10,
          abs(tail(curve$simulated, 1) - 15) < 1e-10)
decreasing <- events; decreasing$simulated <- c(5, 10, 9)
stopifnot(inherits(try(monotone_cumulative_curve(decreasing), silent = TRUE), "try-error"))
stopifnot(line_width_mm(1) > .35, line_width_mm(1) < .36)
source("paper/R/fig_model_performance.R", encoding = "UTF-8")
example <- data.frame(variable = "LAID", variable_label = "LAI", unit = "m2/m2",
  dataset_role = "diagnostic", observed = c(1, 4), simulated = c(1, 2),
  observed_se = NA_real_, simulation_date_gap_days = c(0, 4))
evaluated <- build_model_performance(example, "LAID", load_publication_profile("configs/figures/publication.json"))
stopifnot(evaluated$metrics$n == 1, evaluated$metrics$rmse == 0)
cat("C16 plotting regressions passed: explicit seasons, three harvest nodes, monotonicity, point units.\n")
