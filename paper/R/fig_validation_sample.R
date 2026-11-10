# Six-variable deterministic 1:1 prototype with audited treatment roles.
build_validation_sample <- function(pairs, metrics, profile, is_demo = FALSE) {
  variables <- c("LAID", "LWAD", "SWAD", "FRESH_INC", "FRESH_CUM", "TERMINAL_FRESH")
  titles <- if(isTRUE(profile$mixed_times_simsun)) as.list(c("(a) LAI（m² m⁻²）", "(b) 叶干重（kg ha⁻¹）",
    "(c) 茎干重（kg ha⁻¹）", "(d) 单次采收鲜重（t ha⁻¹）", "(e) 累计采收鲜重（t ha⁻¹）", "(f) 季末鲜果产量（t ha⁻¹）")) else
    list(expression("(a) LAI（" * m^2 ~ m^{-2} * "）"), expression("(b) 叶干重（kg " * ha^{-1} * "）"),
      expression("(c) 茎干重（kg " * ha^{-1} * "）"), expression("(d) 单次采收鲜重（t " * ha^{-1} * "）"),
      expression("(e) 累计采收鲜重（t " * ha^{-1} * "）"), expression("(f) 季末鲜果产量（t " * ha^{-1} * "）"))
  p <- lapply(seq_along(variables), function(i) {
    d <- pairs[pairs$variable == variables[i], ]
    stopifnot(nrow(d) > 0, all(is.finite(d$observed)), all(is.finite(d$simulated)))
    top <- max(c(d$observed, d$simulated)) * 1.07
    panel <- ggplot2::ggplot(d, ggplot2::aes(x = observed, y = simulated, colour = season_id, shape = dataset_role)) +
      ggplot2::geom_abline(slope = 1, intercept = 0, colour = "#7C858C", linewidth = line_width_mm(.7)) +
      ggplot2::geom_point(size = 1.5, alpha = .8, stroke = .55) +
      ggplot2::annotate("text",x=.04*top,y=.95*top,label=paste0("n = ",nrow(d)),
        hjust=0,vjust=1,size=6/ggplot2::.pt,family=profile$font_family[[1]]) +
      ggplot2::scale_colour_manual(values = c("25SP" = "#0072B2", "26SP" = "#D55E00"),
        labels = c("2025年春", "2026年春"), name = NULL) +
      ggplot2::scale_shape_manual(values = c(calibration = 16, validation = 1),
        labels = c(calibration = "率定处理", validation = "留出处理"), name = NULL) +
      ggplot2::scale_x_continuous(limits = c(0, top), expand = c(0, 0), breaks = scales::breaks_pretty(n = 3)) +
      ggplot2::scale_y_continuous(limits = c(0, top), expand = c(0, 0), breaks = scales::breaks_pretty(n = 3)) +
      ggplot2::coord_equal() +
      ggplot2::labs(x = if(isTRUE(profile$stage2_review) && variables[i]=="LAID") "观测/推算值" else "实测值", y = "模拟值", title = titles[[i]]) +
      theme_q1(profile) + ggplot2::theme(legend.position = "bottom", plot.title = ggplot2::element_text(size = 7, face = "bold")) + demo_watermark(is_demo)
    if("observation_origin" %in% names(d)) panel <- panel + ggplot2::geom_point(
      data=d[!is.na(d$observation_origin) & d$observation_origin=="SLA_ratio_derived",],ggplot2::aes(x=observed,y=simulated),
      inherit.aes=FALSE,shape=4,colour="#202020",size=1.8,stroke=.45)
    panel
  })
  combined <- patchwork::wrap_plots(p, ncol = 3, guides = "collect") & ggplot2::theme(legend.position = "bottom")
  caption <- if(isTRUE(profile$stage2_review))
    "C31确定性结果；×标识26SP的12个SLA推算LAI值；同日口径。\n留出评价的历史选模独立性尚未证明。" else
    "样板｜C31 确定性结果；同日工作口径；留出评价的历史选模独立性尚未证明。"
  combined <- combined + patchwork::plot_annotation(caption = caption,
    theme = ggplot2::theme(plot.caption = ggplot2::element_text(family = profile$font_family[[1]], size = 5.7, hjust = 0)))
  list(plot = combined, source = pairs, metrics = metrics[metrics$variant == "baseline" & metrics$date_offset_days == 0, ], height_mm = 128)
}

build_spring_one_to_one <- function(comparison, profile, status_note) {
  variables <- c("TERMINAL_FRESH", "FRESH_CUM", "DRY_CUM", "LAID", "LWAD", "SWAD")
  units <- c(rep("t ha⁻¹", 3), "m² m⁻²", rep("kg ha⁻¹", 2))
  source <- comparison[comparison$variable %in% variables, ]
  metric_rows <- list()
  plots <- lapply(seq_along(variables), function(i) {
    d <- source[source$variable == variables[i], ]
    end <- max(d$observed, d$simulated) * 1.10
    role_label <- c(calibration = "率定集", validation = "验证集")
    m <- do.call(rbind, lapply(names(role_label), function(role) {
      q <- d[d$dataset_role == role, ]
      observed <- q$observed
      simulated <- q$simulated
      center <- mean(observed)
      if (length(observed) < 3 || any(!is.finite(c(observed, simulated))) ||
          center <= 0 || min(stats::sd(observed), stats::sd(simulated)) <= 0) {
        stop("Invalid season/variable evaluation sample: ", role, " / ", variables[i])
      }
      sse <- sum((simulated - observed)^2)
      data.frame(variable = variables[i], dataset_role = role, season_id = unique(q$season_id),
        n = nrow(q), nrmse_pct = sqrt(sse / length(observed)) / center * 100,
        r2 = stats::cor(observed, simulated)^2,
        willmott_d = 1 - sse / sum((abs(simulated - center) + abs(observed - center))^2))
    }))
    metric_rows[[i]] <<- m
    col <- c("25SP" = profile$nitrogen_colors[["N0"]], "26SP" = profile$nitrogen_colors[["N1"]])
    left <- m[m$dataset_role == "calibration", ]
    right <- m[m$dataset_role == "validation", ]
    label <- function(row) sprintf("%s\nNRMSE %.1f%%\nR² %.2f   d %.2f",
      role_label[row$dataset_role], row$nrmse_pct, row$r2, row$willmott_d)
    ggplot2::ggplot(d, ggplot2::aes(observed, simulated, colour = season_id, shape = season_id)) +
      ggplot2::geom_abline(slope = 1, intercept = 0, colour = "#8B9399",
        linewidth = .26, linetype = "dashed") +
      ggplot2::geom_point(size = 1.32, alpha = .83, stroke = .38) +
      ggplot2::annotate("text", x = .035 * end, y = .965 * end, label = label(left),
        hjust = 0, vjust = 1, lineheight = .98, size = 6.2 / ggplot2::.pt,
        family = profile$font_family[[1]], colour = "black") +
      ggplot2::annotate("text", x = .965 * end, y = .035 * end, label = label(right),
        hjust = 1, vjust = 0, lineheight = .98, size = 6.2 / ggplot2::.pt,
        family = profile$font_family[[1]], colour = "black") +
      ggplot2::scale_colour_manual(values = col, breaks = names(col),
        labels = c("2025年", "2026年"), name = NULL) +
      ggplot2::scale_shape_manual(values = c("25SP" = 1, "26SP" = 16), breaks = names(col),
        labels = c("2025年", "2026年"), name = NULL) +
      ggplot2::scale_x_continuous(breaks = scales::breaks_pretty(n = 4), expand = c(0, 0)) +
      ggplot2::scale_y_continuous(breaks = scales::breaks_pretty(n = 4), expand = c(0, 0)) +
      ggplot2::coord_equal(xlim = c(0, end), ylim = c(0, end), expand = FALSE) +
      ggplot2::labs(x = paste0("实测值（", units[i], "）"), y = paste0("模拟值（", units[i], "）"),
        title = paste0("(", letters[i], ")")) +
      theme_q1(profile) +
      ggplot2::theme(plot.title = ggplot2::element_text(size = profile$panel_label_size_pt),
        axis.title = ggplot2::element_text(colour = "black"),
        axis.text = ggplot2::element_text(colour = "black"),
        panel.grid.major = ggplot2::element_line(colour = "#E9EDF0", linewidth = .19))
  })
  plot <- patchwork::wrap_plots(plots, ncol = 3, guides = "collect") +
    patchwork::plot_annotation(caption = status_note, theme = spring_caption_theme(profile) +
      ggplot2::theme(plot.caption = ggplot2::element_text(colour = "black")))
  plot <- plot & ggplot2::theme(legend.position = "bottom", legend.justification = "center",
    legend.text = ggplot2::element_text(colour = "black"))
  list(plot = plot, source = source, metrics = do.call(rbind, metric_rows), height_mm = 134)
}
