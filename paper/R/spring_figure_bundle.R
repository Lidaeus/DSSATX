read_spring_figure_bundle <- function(input_dir, allow_demo = FALSE) {
  manifest <- jsonlite::fromJSON(file.path(input_dir, "paper_data_manifest.json"), simplifyVector = FALSE)
  if (!identical(manifest$bundle_type, "spring_deterministic_figures")) {
    stop("Spring figures require the frozen deterministic spring bundle")
  }
  is_demo <- !identical(manifest$data_status, "science_validated") ||
    !identical(manifest$engineering_status, "engineering_passed")
  if (is_demo && !isTRUE(allow_demo)) {
    stop("Spring figures are review-only; use --allow-unvalidated-demo")
  }
  files <- c(comparison = "comparison.csv", trajectory = "simulation_trajectory.csv",
             selection = "representative_treatments.csv", metadata = "treatment_metadata.csv")
  paths <- vapply(manifest$artifacts, function(a) a$path, character(1))
  if (anyDuplicated(paths) || !setequal(paths, unname(files))) stop("Unexpected or missing spring figure tables")
  tables <- lapply(files, function(name) {
    path <- file.path(input_dir, name)
    if (!identical(sha256_file(path), manifest$artifacts[[match(name, paths)]]$sha256)) {
      stop("Spring figure artifact hash mismatch: ", name)
    }
    utils::read.csv(path, fileEncoding = "UTF-8", check.names = FALSE)
  })
  comparison <- validate_comparison(tables$comparison)
  trajectory <- validate_trajectory(tables$trajectory)
  metadata <- validate_treatment_metadata(tables$metadata)
  if (nrow(comparison) != nrow(tables$comparison) || nrow(trajectory) != nrow(tables$trajectory) ||
      anyDuplicated(comparison[c("season_id", "treatment", "variable", "date")]) ||
      anyDuplicated(trajectory[c("season_id", "treatment", "variable", "date")])) {
    stop("Nonfinite or duplicate spring figure rows")
  }
  roles <- c("26SP" = "calibration", "25SP" = "validation")
  key <- function(d) paste(d$season_id, d$treatment)
  for (d in list(comparison, trajectory, metadata, tables$selection)) {
    if (!all(key(d) %in% key(metadata)) ||
        !identical(as.character(d$dataset_role), unname(roles[d$season_id]))) {
      stop("Spring figure season or treatment roles do not match the bundle")
    }
  }
  list(manifest = manifest, is_demo = is_demo, comparison = comparison,
       trajectory = trajectory, selection = tables$selection)
}

spring_management_scales <- function(selection, profile, treatment_order) {
  meta <- unique(selection[c("management", "water_level", "nitrogen_level")])
  stopifnot(!anyDuplicated(meta$management), setequal(meta$management, treatment_order))
  list(colors = setNames(unlist(profile$nitrogen_colors)[meta$nitrogen_level], meta$management),
       shapes = setNames(unlist(profile$water_shapes)[meta$water_level], meta$management))
}

spring_caption_theme <- function(profile) {
  ggplot2::theme(plot.caption = ggplot2::element_text(family = profile$font_family[[1]],
    hjust = 0, size = 6.4, colour = "#53616A"))
}
