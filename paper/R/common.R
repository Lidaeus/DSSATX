required_packages <- c("ggplot2", "patchwork", "jsonlite", "svglite")

check_r_dependencies <- function() {
  missing <- required_packages[!vapply(required_packages, requireNamespace, logical(1), quietly = TRUE)]
  if (length(missing) > 0) {
    stop("Missing R packages: ", paste(missing, collapse = ", "), call. = FALSE)
  }
}

parse_cli_args <- function(values) {
  result <- list()
  index <- 1L
  while (index <= length(values)) {
    token <- values[[index]]
    if (!startsWith(token, "--")) stop("Unexpected argument: ", token, call. = FALSE)
    key <- gsub("-", "_", substring(token, 3), fixed = TRUE)
    if (key == "allow_unvalidated_demo") {
      result[[key]] <- TRUE
      index <- index + 1L
    } else {
      if (index == length(values)) stop("Missing value for ", token, call. = FALSE)
      result[[key]] <- values[[index + 1L]]
      index <- index + 2L
    }
  }
  result
}

require_arg <- function(args, name) {
  value <- args[[name]]
  if (is.null(value) || !nzchar(value)) stop("Missing --", gsub("_", "-", name), call. = FALSE)
  value
}

split_csv_arg <- function(value) {
  trimws(strsplit(value, ",", fixed = TRUE)[[1]])
}

load_publication_profile <- function(path) {
  profile <- jsonlite::fromJSON(path, simplifyVector = TRUE)
  required <- c("profile_id", "column_width_mm", "double_column_width_mm",
                "font_size_pt", "raster_dpi", "formats", "palette",
                "nitrogen_colors", "water_shapes")
  missing <- setdiff(required, names(profile))
  if (length(missing) > 0) stop("Figure profile missing: ", paste(missing, collapse = ", "))
  if (profile$font_size_pt < 5) stop("Final-size font must be at least 5 pt")
  if (profile$raster_dpi < 300) stop("Raster export must be at least 300 dpi")
  profile
}

theme_q1 <- function(profile) {
  family <- profile$font_family[[1]]
  ggplot2::theme_classic(base_size = profile$font_size_pt, base_family = family) +
    ggplot2::theme(
      plot.title = ggplot2::element_text(face = "bold", size = profile$font_size_pt),
      plot.subtitle = ggplot2::element_text(colour = "#4D4D4D", margin = ggplot2::margin(b = 5)),
      plot.caption = ggplot2::element_text(colour = "#666666", size = 5, hjust = 1),
      axis.title = ggplot2::element_text(colour = "#222222"),
      axis.text = ggplot2::element_text(colour = "#333333"),
      axis.line = ggplot2::element_line(linewidth = profile$axes_linewidth_pt, colour = "#333333"),
      axis.ticks = ggplot2::element_line(linewidth = profile$axes_linewidth_pt, colour = "#333333"),
      legend.position = "top",
      legend.justification = "left",
      legend.title = ggplot2::element_blank(),
      legend.key = ggplot2::element_blank(),
      panel.grid = ggplot2::element_blank(),
      plot.background = ggplot2::element_rect(fill = "white", colour = NA),
      panel.background = ggplot2::element_rect(fill = "white", colour = NA)
    )
}

demo_caption <- function(is_demo) {
  if (isTRUE(is_demo)) "DEMO — unvalidated historical data; layout review only" else NULL
}

save_figure_set <- function(plot, output_base, profile, width_mm, height_mm, formats = profile$formats) {
  dir.create(dirname(output_base), recursive = TRUE, showWarnings = FALSE)
  paths <- character()
  for (format in tolower(formats)) {
    path <- paste0(output_base, ".", format)
    if (format == "pdf") {
      ggplot2::ggsave(path, plot, width = width_mm, height = height_mm, units = "mm",
                      device = grDevices::cairo_pdf, limitsize = FALSE)
    } else if (format == "svg") {
      ggplot2::ggsave(path, plot, width = width_mm, height = height_mm, units = "mm",
                      device = svglite::svglite, limitsize = FALSE)
    } else if (format == "png") {
      ggplot2::ggsave(path, plot, width = width_mm, height = height_mm, units = "mm",
                      dpi = profile$raster_dpi, bg = "white", limitsize = FALSE)
    } else {
      stop("Unsupported figure format: ", format, call. = FALSE)
    }
    paths <- c(paths, normalizePath(path, winslash = "/", mustWork = TRUE))
  }
  paths
}

validate_comparison <- function(data) {
  required <- c("run_id", "data_status", "dataset_role", "variable", "variable_label",
                "unit", "treatment", "time", "time_label", "observed", "simulated", "source_file")
  missing <- setdiff(required, names(data))
  if (length(missing) > 0) stop("comparison.csv missing: ", paste(missing, collapse = ", "))
  data$observed <- as.numeric(data$observed)
  data$simulated <- as.numeric(data$simulated)
  data$time <- as.numeric(data$time)
  optional_numeric <- c("date_code", "year", "doy", "dap", "harvest_number",
                        "observed_sd", "observed_se", "n_rep")
  for (column in optional_numeric) {
    if (!column %in% names(data)) data[[column]] <- NA_real_
    data[[column]] <- as.numeric(data[[column]])
  }
  data <- data[is.finite(data$observed) & is.finite(data$simulated), , drop = FALSE]
  if (nrow(data) == 0) stop("comparison.csv has no finite pairs")
  data
}

validate_trajectory <- function(data) {
  required <- c("run_id", "data_status", "dataset_role", "variable", "variable_label",
                "unit", "treatment", "time", "time_label", "year", "doy", "date_code",
                "simulated", "statistic", "source_file")
  missing <- setdiff(required, names(data))
  if (length(missing) > 0) stop("simulation_trajectory.csv missing: ", paste(missing, collapse = ", "))
  for (column in c("time", "year", "doy", "date_code", "simulated")) {
    data[[column]] <- as.numeric(data[[column]])
  }
  data <- data[is.finite(data$time) & is.finite(data$simulated), , drop = FALSE]
  if (nrow(data) == 0) stop("simulation_trajectory.csv has no finite values")
  data
}

validate_treatment_metadata <- function(data) {
  required <- c("treatment", "treatment_label", "water_level", "nitrogen_level")
  missing <- setdiff(required, names(data))
  if (length(missing) > 0) stop("treatment_metadata.csv missing: ", paste(missing, collapse = ", "))
  for (column in required) {
    data[[column]] <- trimws(as.character(data[[column]]))
    if (any(!nzchar(data[[column]]))) stop("Treatment metadata has blank ", column)
  }
  if (anyDuplicated(data$treatment)) stop("Treatment metadata has duplicate treatment identifiers")
  data
}

read_paper_bundle <- function(input_dir, allow_demo = FALSE) {
  manifest_path <- file.path(input_dir, "paper_data_manifest.json")
  if (!file.exists(manifest_path)) stop("Missing paper_data_manifest.json in ", input_dir)
  manifest <- jsonlite::fromJSON(manifest_path, simplifyVector = FALSE)
  for (artifact in manifest$artifacts) {
    artifact_path <- file.path(input_dir, artifact$path)
    if (!file.exists(artifact_path)) stop("Manifest artifact is missing: ", artifact$path)
    actual <- sha256_file(artifact_path)
    if (!identical(tolower(actual), tolower(artifact$sha256))) {
      stop("Manifest hash mismatch: ", artifact$path)
    }
  }
  is_demo <- !identical(manifest$data_status, "science_validated")
  if (is_demo && !isTRUE(allow_demo)) {
    stop("Input is not science_validated; use --allow-unvalidated-demo only for layout QA")
  }
  comparison <- validate_comparison(utils::read.csv(file.path(input_dir, "comparison.csv"),
                                                    stringsAsFactors = FALSE, check.names = FALSE))
  phi_path <- file.path(input_dir, "phi_ensemble.csv")
  phi <- if (file.exists(phi_path)) utils::read.csv(phi_path, stringsAsFactors = FALSE) else NULL
  trajectory_path <- file.path(input_dir, "simulation_trajectory.csv")
  trajectory <- if (file.exists(trajectory_path)) {
    validate_trajectory(utils::read.csv(trajectory_path, stringsAsFactors = FALSE, check.names = FALSE))
  } else NULL
  metadata_path <- file.path(input_dir, "treatment_metadata.csv")
  treatment_metadata <- if (file.exists(metadata_path)) {
    validate_treatment_metadata(utils::read.csv(metadata_path, stringsAsFactors = FALSE, check.names = FALSE))
  } else NULL
  list(manifest = manifest, comparison = comparison, phi = phi, trajectory = trajectory,
       treatment_metadata = treatment_metadata, is_demo = is_demo)
}

require_calibration_scenario <- function(bundle) {
  if (isTRUE(bundle$is_demo)) return(invisible(TRUE))
  scenario <- bundle$manifest$scenario_type
  if (!identical(scenario, "actual_trial_calibration")) {
    stop("Formal calibration figures require scenario_type=actual_trial_calibration", call. = FALSE)
  }
  frozen <- bundle$manifest$upstream_validation$frozen_run_inputs
  required <- c("input_manifest_sha256", "bounds_sha256", "observation_policy_sha256", "validation_split_sha256")
  if (is.null(frozen) || !all(required %in% names(frozen))) {
    stop("Formal calibration figures require frozen input/bounds/policy/split provenance", call. = FALSE)
  }
  invisible(TRUE)
}

read_t4_demo_bundle <- function(input_dir, allow_demo = FALSE) {
  manifest_path <- file.path(input_dir, "paper_data_manifest.json")
  if (!file.exists(manifest_path)) stop("Missing paper_data_manifest.json in ", input_dir)
  manifest <- jsonlite::fromJSON(manifest_path, simplifyVector = FALSE)
  if (!identical(manifest$bundle_type, "t4_posterior_equifinality")) {
    stop("This renderer requires bundle_type=t4_posterior_equifinality", call. = FALSE)
  }
  for (artifact in manifest$artifacts) {
    artifact_path <- file.path(input_dir, artifact$path)
    if (!file.exists(artifact_path)) stop("Manifest artifact is missing: ", artifact$path)
    if (!identical(tolower(sha256_file(artifact_path)), tolower(artifact$sha256))) {
      stop("Manifest hash mismatch: ", artifact$path)
    }
  }
  is_demo <- !identical(manifest$data_status, "science_validated")
  if (is_demo && !isTRUE(allow_demo)) {
    stop("Input is not science_validated; use --allow-unvalidated-demo only for layout QA")
  }
  required <- c("posterior_diagnostics.csv", "spearman_correlation.csv", "candidate_pairs.csv",
                "candidate_pair_predictions.csv")
  missing <- required[!file.exists(file.path(input_dir, required))]
  if (length(missing) > 0) stop("T4 bundle missing: ", paste(missing, collapse = ", "))
  read_csv <- function(name) utils::read.csv(file.path(input_dir, name), stringsAsFactors = FALSE,
                                              check.names = FALSE)
  bundle <- list(manifest = manifest, is_demo = is_demo,
                 posterior = read_csv("posterior_diagnostics.csv"),
                 spearman = read_csv("spearman_correlation.csv"),
                 pairs = read_csv("candidate_pairs.csv"),
                 pair_predictions = read_csv("candidate_pair_predictions.csv"))
  for (table in bundle[c("posterior", "spearman", "pairs", "pair_predictions")]) {
    if (!all(c("run_id", "data_status") %in% names(table))) stop("T4 table lacks provenance columns")
    if (length(unique(table$run_id)) != 1 || unique(table$run_id)[[1]] != manifest$run_id) {
      stop("T4 table run_id does not match manifest")
    }
  }
  bundle
}

read_sa_bundle <- function(input_dir, allow_demo = FALSE) {
  manifest_path <- file.path(input_dir, "paper_data_manifest.json")
  if (!file.exists(manifest_path)) stop("Missing paper_data_manifest.json in ", input_dir)
  manifest <- jsonlite::fromJSON(manifest_path, simplifyVector = FALSE)
  if (!identical(manifest$bundle_type, "morris_sa_evidence")) {
    stop("SA figures require bundle_type=morris_sa_evidence", call. = FALSE)
  }
  required <- c(
    "morris_season_rankings.csv", "morris_cross_season_summary.csv",
    "morris_seed_rankings.csv", "morris_group_scores.csv",
    "morris_group_summary.csv", "morris_pairwise_stability.csv",
    "morris_focus_parameters.csv"
  )
  listed <- vapply(manifest$artifacts, function(artifact) artifact$path, character(1))
  missing_manifest <- setdiff(required, listed)
  if (length(missing_manifest) > 0) {
    stop("SA manifest does not bind required artifacts: ", paste(missing_manifest, collapse = ", "))
  }
  for (artifact in manifest$artifacts) {
    if (!identical(basename(artifact$path), artifact$path)) {
      stop("SA manifest artifact path must be a local filename: ", artifact$path)
    }
    artifact_path <- file.path(input_dir, artifact$path)
    if (!file.exists(artifact_path)) stop("Manifest artifact is missing: ", artifact$path)
    if (!identical(tolower(sha256_file(artifact_path)), tolower(artifact$sha256))) {
      stop("Manifest hash mismatch: ", artifact$path)
    }
  }
  is_demo <- !identical(manifest$data_status, "science_validated")
  if (is_demo && !isTRUE(allow_demo)) {
    stop("SA input is not science_validated; use --allow-unvalidated-demo only for current-evidence/layout QA")
  }
  missing <- required[!file.exists(file.path(input_dir, required))]
  if (length(missing) > 0) stop("SA bundle missing: ", paste(missing, collapse = ", "))
  read_csv <- function(name) utils::read.csv(
    file.path(input_dir, name), stringsAsFactors = FALSE, check.names = FALSE
  )
  bundle <- list(
    manifest = manifest,
    is_demo = is_demo,
    rankings = read_csv("morris_season_rankings.csv"),
    summary = read_csv("morris_cross_season_summary.csv"),
    seed_rankings = read_csv("morris_seed_rankings.csv"),
    group_scores = read_csv("morris_group_scores.csv"),
    group_summary = read_csv("morris_group_summary.csv"),
    stability = read_csv("morris_pairwise_stability.csv"),
    focus = read_csv("morris_focus_parameters.csv")
  )
  # W4 (plan §5.3): the response-level mu*-sigma table is optional.  When the
  # bundle carries it (via a sibling morris_response_effects.csv bound in the
  # manifest), it enables the response-effects small-multiples panel.
  effects_name <- "morris_response_effects.csv"
  if (effects_name %in% listed) {
    bundle$effects <- read_csv(effects_name)
    bundle$has_effects <- TRUE
  } else {
    bundle$effects <- NULL
    bundle$has_effects <- FALSE
  }
  provenance_tables <- c("rankings", "summary", "seed_rankings", "group_scores",
                         "group_summary", "stability", "focus")
  # P1#2: the optional effects table must pass the same provenance check when
  # present, so a mismatched run_id/data_status cannot slip into the figure.
  if (isTRUE(bundle$has_effects) && !is.null(bundle$effects)) {
    provenance_tables <- c(provenance_tables, "effects")
  }
  for (name in provenance_tables) {
    table <- bundle[[name]]
    if (!all(c("run_id", "data_status") %in% names(table)) || nrow(table) == 0) {
      stop("SA table '", name, "' lacks provenance columns or is empty")
    }
    if (length(unique(table$run_id)) != 1 || unique(table$run_id)[[1]] != manifest$run_id) {
      stop("SA table '", name, "' run_id does not match manifest (got ",
           unique(table$run_id)[[1]], ", expected ", manifest$run_id, ")")
    }
    if (length(unique(table$data_status)) != 1 || unique(table$data_status)[[1]] != manifest$data_status) {
      stop("SA table '", name, "' data_status does not match manifest (got ",
           unique(table$data_status)[[1]], ", expected ", manifest$data_status, ")")
    }
  }
  bundle
}

read_sobol_bundle <- function(input_dir, allow_demo = FALSE) {
  manifest_path <- file.path(input_dir, "paper_data_manifest.json")
  if (!file.exists(manifest_path)) stop("Missing paper_data_manifest.json in ", input_dir)
  manifest <- jsonlite::fromJSON(manifest_path, simplifyVector = FALSE)
  allowed_types <- c("sobol_convergence_evidence", "sobol_multiseason_stability_evidence")
  if (!manifest$bundle_type %in% allowed_types) {
    stop("Sobol figures require a supported Sobol evidence bundle", call. = FALSE)
  }
  is_multiseason <- identical(manifest$bundle_type, "sobol_multiseason_stability_evidence")
  listed <- vapply(manifest$artifacts, function(artifact) artifact$path, character(1))
  has_effects <- all(c("sobol_effect_decomposition.csv", "sobol_response_scales.csv") %in% listed)
  required <- if (is_multiseason) {
    c("sobol_scale_rankings.csv", "sobol_convergence_metrics.csv", "sobol_run_scale.csv", "sobol_stability_summary.csv")
  } else {
    c("sobol_scale_rankings.csv", "sobol_scale_group_scores.csv",
      "sobol_convergence_comparisons.csv", "sobol_convergence_metrics.csv",
      "sobol_run_scale.csv", "sobol_convergence.json")
  }
  missing_manifest <- setdiff(required, listed)
  if (length(missing_manifest) > 0) {
    stop("Sobol manifest does not bind required artifacts: ", paste(missing_manifest, collapse = ", "))
  }
  for (artifact in manifest$artifacts) {
    if (!identical(basename(artifact$path), artifact$path)) {
      stop("Sobol manifest artifact path must be a local filename: ", artifact$path)
    }
    artifact_path <- file.path(input_dir, artifact$path)
    if (!file.exists(artifact_path)) stop("Manifest artifact is missing: ", artifact$path)
    if (!identical(tolower(sha256_file(artifact_path)), tolower(artifact$sha256))) {
      stop("Manifest hash mismatch: ", artifact$path)
    }
  }
  is_demo <- !identical(manifest$data_status, "science_validated")
  if (is_demo && !isTRUE(allow_demo)) {
    stop("Sobol input is not science_validated; use --allow-unvalidated-demo only for current-evidence/layout QA")
  }
  read_csv <- function(name) utils::read.csv(file.path(input_dir, name), stringsAsFactors = FALSE,
                                              check.names = FALSE)
  bundle <- list(
    manifest = manifest, is_demo = is_demo,
    rankings = read_csv("sobol_scale_rankings.csv"),
    metrics = read_csv("sobol_convergence_metrics.csv"),
    run_scale = read_csv("sobol_run_scale.csv"),
    summary = if (is_multiseason) read_csv("sobol_stability_summary.csv") else NULL,
    effects = if (has_effects) read_csv("sobol_effect_decomposition.csv") else NULL,
    response_scales = if (has_effects) read_csv("sobol_response_scales.csv") else NULL,
    is_multiseason = is_multiseason,
    has_effects = has_effects
  )
  # P1#2: validate provenance on every present table, including the optional
  # summary / effects / response_scales.  The base tables (rankings, metrics,
  # run_scale) are always present; the others are present only when the bundle
  # carries the effect decomposition.  Every present table must carry matching
  # run_id/data_status and be non-empty.
  sobol_tables <- c("rankings", "metrics", "run_scale")
  if (!is.null(bundle$summary)) sobol_tables <- c(sobol_tables, "summary")
  if (isTRUE(has_effects)) sobol_tables <- c(sobol_tables, "effects", "response_scales")
  for (name in sobol_tables) {
    table <- bundle[[name]]
    if (is.null(table)) next
    if (!all(c("run_id", "data_status") %in% names(table)) || nrow(table) == 0) {
      stop("Sobol table '", name, "' lacks provenance columns or is empty")
    }
    if (length(unique(table$run_id)) != 1 || unique(table$run_id)[[1]] != manifest$run_id) {
      stop("Sobol table '", name, "' run_id does not match manifest (got ",
           unique(table$run_id)[[1]], ", expected ", manifest$run_id, ")")
    }
    if (length(unique(table$data_status)) != 1 || unique(table$data_status)[[1]] != manifest$data_status) {
      stop("Sobol table '", name, "' data_status does not match manifest (got ",
           unique(table$data_status)[[1]], ", expected ", manifest$data_status, ")")
    }
  }
  bundle
}

demo_watermark <- function(is_demo) {
  if (!isTRUE(is_demo)) return(NULL)
  ggplot2::annotate("text", x = Inf, y = Inf, label = "DEMO", hjust = 1.15, vjust = 1.5,
                    colour = "#7A7A7A", alpha = 0.55, fontface = "bold", size = 3)
}

sha256_record <- function(path) {
  list(path = normalizePath(path, winslash = "/", mustWork = TRUE),
       sha256 = sha256_file(path))
}

sha256_file <- function(path) {
  path <- normalizePath(path, winslash = "/", mustWork = TRUE)
  if (.Platform$OS.type == "windows") {
    output <- system2("certutil", c("-hashfile", shQuote(path), "SHA256"),
                      stdout = TRUE, stderr = TRUE)
    candidates <- gsub("[^0-9A-Fa-f]", "", output)
    candidates <- candidates[nchar(candidates) == 64]
    if (length(candidates) == 0) stop("Unable to compute SHA-256 for ", path)
    return(tolower(candidates[[1]]))
  }
  executable <- Sys.which("sha256sum")
  if (!nzchar(executable)) stop("sha256sum is required on non-Windows systems")
  output <- system2(executable, shQuote(path), stdout = TRUE, stderr = TRUE)
  tolower(strsplit(output[[1]], "[[:space:]]+")[[1]][[1]])
}
