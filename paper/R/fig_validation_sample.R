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
