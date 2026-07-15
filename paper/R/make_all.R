script_arg <- grep("^--file=", commandArgs(trailingOnly = FALSE), value = TRUE)
script_path <- normalizePath(sub("^--file=", "", script_arg[[1]]), winslash = "/", mustWork = TRUE)
script_dir <- dirname(script_path)
project_root <- normalizePath(file.path(script_dir, "..", ".."), winslash = "/", mustWork = TRUE)

source(file.path(script_dir, "common.R"), local = FALSE)
source(file.path(script_dir, "fig_model_performance.R"), local = FALSE)
source(file.path(script_dir, "fig_selected_dynamics.R"), local = FALSE)
source(file.path(script_dir, "fig_phi_convergence.R"), local = FALSE)

check_r_dependencies()
args <- parse_cli_args(commandArgs(trailingOnly = TRUE))
input_dir <- normalizePath(require_arg(args, "input_dir"), winslash = "/", mustWork = TRUE)
out_dir <- require_arg(args, "out_dir")
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
out_dir <- normalizePath(out_dir, winslash = "/", mustWork = TRUE)
profile_path <- if (is.null(args$profile)) file.path(project_root, "configs", "figures", "publication.json") else args$profile
profile <- load_publication_profile(profile_path)
if (!is.null(args$formats)) profile$formats <- split_csv_arg(args$formats)

bundle <- read_paper_bundle(input_dir, isTRUE(args$allow_unvalidated_demo))
variables <- split_csv_arg(if (is.null(args$variables)) "LAID,LWAD,SWAD,FRESH_INC" else args$variables)
timeseries_variables <- split_csv_arg(if (is.null(args$timeseries_variables)) "LAID,FRESH_INC" else args$timeseries_variables)
treatments <- split_csv_arg(if (is.null(args$treatments)) "2,13" else args$treatments)
stem <- if (bundle$is_demo) "DEMO" else "Fig"
artifacts <- character()

performance <- build_model_performance(bundle$comparison, variables, profile, bundle$is_demo)
performance_base <- file.path(out_dir, paste0(stem, if (bundle$is_demo) "_model_performance" else "3_model_performance"))
artifacts <- c(artifacts, save_figure_set(performance$plot, performance_base, profile,
                                         profile$double_column_width_mm, performance$height_mm))
performance_source <- paste0(performance_base, ".source.csv")
performance_metrics <- paste0(performance_base, ".metrics.csv")
utils::write.csv(performance$source, performance_source, row.names = FALSE, fileEncoding = "UTF-8")
utils::write.csv(performance$metrics, performance_metrics, row.names = FALSE, fileEncoding = "UTF-8")
artifacts <- c(artifacts, performance_source, performance_metrics)

dynamics <- build_selected_dynamics(bundle$comparison, timeseries_variables, treatments, profile, bundle$is_demo)
dynamics_base <- file.path(out_dir, paste0(stem, if (bundle$is_demo) "_selected_dynamics" else "4_selected_dynamics"))
artifacts <- c(artifacts, save_figure_set(dynamics$plot, dynamics_base, profile,
                                         profile$double_column_width_mm, dynamics$height_mm))
dynamics_source <- paste0(dynamics_base, ".source.csv")
utils::write.csv(dynamics$source, dynamics_source, row.names = FALSE, fileEncoding = "UTF-8")
artifacts <- c(artifacts, dynamics_source)

if (!is.null(bundle$phi)) {
  convergence <- build_phi_convergence(bundle$phi, profile, bundle$is_demo)
  convergence_base <- file.path(out_dir, paste0(stem, if (bundle$is_demo) "_phi_convergence" else "2_phi_convergence"))
  artifacts <- c(artifacts, save_figure_set(convergence$plot, convergence_base, profile,
                                           profile$column_width_mm, convergence$height_mm))
  convergence_source <- paste0(convergence_base, ".source.csv")
  convergence_summary <- paste0(convergence_base, ".summary.csv")
  utils::write.csv(convergence$source, convergence_source, row.names = FALSE, fileEncoding = "UTF-8")
  utils::write.csv(convergence$summary, convergence_summary, row.names = FALSE, fileEncoding = "UTF-8")
  artifacts <- c(artifacts, convergence_source, convergence_summary)
}

manifest <- list(
  schema_version = 1,
  created_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC"),
  renderer = paste0("R ", getRversion()),
  package_versions = as.list(vapply(required_packages,
    function(package) as.character(utils::packageVersion(package)), character(1))),
  git_commit = trimws(system2("git", c("-C", shQuote(project_root), "rev-parse", "HEAD"),
                              stdout = TRUE, stderr = FALSE)[[1]]),
  git_dirty = length(system2("git", c("-C", shQuote(project_root), "status", "--porcelain"),
                             stdout = TRUE, stderr = FALSE)) > 0,
  profile_id = profile$profile_id,
  profile = sha256_record(profile_path),
  run_id = bundle$manifest$run_id,
  data_status = if (bundle$is_demo) "legacy_layout_demo" else "science_validated",
  input_manifest = sha256_record(file.path(input_dir, "paper_data_manifest.json")),
  artifacts = lapply(artifacts, sha256_record)
)
manifest_path <- file.path(out_dir, "figure_manifest.json")
jsonlite::write_json(manifest, manifest_path, auto_unbox = TRUE, pretty = TRUE)
cat(normalizePath(manifest_path, winslash = "/", mustWork = TRUE), "\n")
