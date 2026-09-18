# Explicit synthetic layout QA only; not a scientific figure.
source("paper/R/common.R")
source("paper/R/fig_model_performance.R")
source("paper/R/fig_selected_dynamics.R")
source("paper/R/fig_all_treatment_dynamics.R")
source("paper/R/fig_leaf_nitrogen.R")
check_r_dependencies()
profile <- load_publication_profile("configs/figures/publication.json")
sample <- data.frame(variable = "LAID", dataset_role = "diagnostic", observed = c(1, 2, 3),
                     simulated = c(1.1, 1.9, 2.9), observed_se = c(NA, .1, 7),
                     variable_label = "LAI", unit = "m2/m2", treatment = "1")
one <- build_model_performance(sample, "LAID", profile, TRUE)
panel <- one$plot[[1]]
stopifnot(panel$coordinates$limits$x[[1]] < -4, panel$coordinates$limits$x[[2]] > 10)
stopifnot(identical(panel$coordinates$limits$x, panel$coordinates$limits$y))
two <- rbind(transform(sample, season_id = "25SP"), transform(sample, season_id = "26SP"))
result <- build_model_performance(two, "LAID", profile, TRUE)
stopifnot(nrow(result$metrics) == 2, setequal(result$metrics$season_id, c("25SP", "26SP")))
events <- data.frame(dap = c(10, 20), sim_median = c(2, 3), observed = c(1, 4),
                     treatment = "1", water_level = "W1", nitrogen_level = "N0")
labels <- data.frame(water_level = "W1", nitrogen_level = "N0", tn_role = "TN1 [Diag]")
p <- conditional_matrix_plot(events, events, labels, c(0, 5), "Yield", "Test",
                             profile, TRUE, ribbons = FALSE, incremental = TRUE)
stopifnot(any(vapply(p$layers, function(layer) inherits(layer$geom, "GeomSegment"), logical(1))))
stopifnot(!any(vapply(p$layers, function(layer) inherits(layer$geom, "GeomLine"), logical(1))))

# Leaf nitrogen layout QA
tmt_meta <- data.frame(
  season_id = c("25SP", "25SP"), treatment = c("2", "13"),
  treatment_label = c("TN2 (W3-N3)", "TN13 (W1-N0)"),
  water_level = c("W3", "W1"), nitrogen_level = c("N3", "N0"),
  stringsAsFactors = FALSE
)
comp_leaf <- data.frame(
  run_id = "case", data_status = "legacy_unvalidated", dataset_role = c("calibration", "calibration"),
  variable = "LN%D", variable_label = "Leaf nitrogen concentration", unit = "%",
  treatment = c("2", "13"), time = c(119, 119), time_label = "Days after planting",
  observed = c(4.6, 4.3), simulated = c(7.6, 20.1), observed_se = c(0.27, 0.20),
  season_id = c("25SP", "25SP"), stringsAsFactors = FALSE
)
traj_leaf <- data.frame(
  run_id = "case", data_status = "legacy_unvalidated", dataset_role = "calibration",
  variable = "LN%D", variable_label = "Leaf nitrogen concentration", unit = "%",
  treatment = rep(c("2", "13"), each = 10), time = rep(seq(10, 100, length.out = 10), 2),
  time_label = "Days after planting", year = 2025, doy = 100, date_code = 25100,
  simulated = rep(seq(4.5, 7.5, length.out = 10), 2), statistic = "deterministic",
  source_file = "PlantGro.OUT", stringsAsFactors = FALSE
)
leaf_res <- build_leaf_nitrogen(comp_leaf, traj_leaf, tmt_meta, profile, is_demo = TRUE)
stopifnot(!is.null(leaf_res$plot), nrow(leaf_res$metrics) == 1, leaf_res$metrics$n == 2)
stopifnot(leaf_res$metrics$rmse > 0, !is.null(leaf_res$daily))

args <- commandArgs(trailingOnly = TRUE)
if (length(args)) {
  dir.create(args[[1]], recursive = TRUE, showWarnings = FALSE)
  ggplot2::ggsave(file.path(args[[1]], "DEMO_layout_regression.png"), result$plot,
                 width = 183, height = 150, units = "mm", dpi = 150)
}
cat("R layout regression: PASS\n")
