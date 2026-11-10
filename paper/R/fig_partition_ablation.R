read_refitted_partition_bundle <- function(input_dir, allow_demo = FALSE) {
  manifest <- jsonlite::fromJSON(file.path(input_dir, "paper_data_manifest.json"), simplifyVector = FALSE)
  if (!identical(manifest$bundle_type, "refitted_partition_ablation")) stop("Wrong Fig8 bundle type")
  runs <- manifest$runs
  if (!setequal(names(runs), c("full", "reduced"))) stop("Fig8 requires two independently fitted configurations")
  is_demo <- !identical(manifest$data_status, "science_validated") ||
    !all(vapply(runs, function(r) identical(r$engineering_status, "engineering_passed"), logical(1)))
  if (is_demo && !isTRUE(allow_demo)) stop("Fig8 is review-only; use --allow-unvalidated-demo")
  paths <- vapply(manifest$artifacts, function(a) a$path, character(1))
  expected <- c("partition_function.csv", "ablation_metrics.csv", "matched_comparison.csv")
  if (anyDuplicated(paths) || !setequal(paths, expected)) stop("Unexpected or missing Fig8 tables")
  for (a in manifest$artifacts) {
    if (!identical(sha256_file(file.path(input_dir, a$path)), a$sha256)) stop("Fig8 hash mismatch: ", a$path)
  }
  read_csv <- function(name) utils::read.csv(file.path(input_dir, name), fileEncoding = "UTF-8")
  list(manifest = manifest, is_demo = is_demo, curve = read_csv(expected[1]), metrics = read_csv(expected[2]))
}

build_refitted_partition <- function(bundle, profile, is_demo = FALSE,
                                     metric = "nrmse_pct", include_terminal_yield = TRUE) {
  colours <- c(full = "#2980B9", reduced = "#707070")
  variants <- c(full = "保留两参数（58 项）", reduced = "移除两参数（56 项）")
  scale_variant <- function() ggplot2::scale_colour_manual(values = colours, breaks = names(variants),
    labels = variants, name = NULL)
  variables <- c("TERMINAL_FRESH", "FRESH_CUM", "FRESH_INC", "LAID", "LWAD", "SWAD")
  labels <- c("季末鲜果产量", "累计采收鲜重", "单次采收鲜重", "LAI", "叶干重", "茎干重")
  if (identical(bundle$manifest$growth_scope, "season_end")) {
    labels[4:6] <- c("季末 LAI", "季末叶干重", "季末茎干重")
  }
  curve <- bundle$curve
  m <- bundle$metrics
  stopifnot(metric %in% c("nrmse_pct", "r2"), nrow(m) == 24L, all(m$n > 0),
    !anyDuplicated(m[c("variable", "season_id", "variant")]),
    setequal(m$variable, variables), setequal(m$season_id, c("26SP", "25SP")),
    setequal(m$variant, names(variants)))
  if (!include_terminal_yield) {
    m <- m[m$variable != "TERMINAL_FRESH", ]
    variables <- variables[-1]
    labels <- labels[-1]
  }
  metrics <- m
  m$score <- m[[metric]]
  stopifnot(all(is.finite(m$score)))
  if (metric == "r2") stopifnot(all(m$score >= 0 & m$score <= 1))
  m$variable <- factor(m$variable, levels = rev(variables))
  m$season <- factor(m$season_id, levels = c("26SP", "25SP"),
                     labels = c("2026 年率定", "2025 年验证"))
  links <- reshape(m[c("variable", "season", "variant", "score")], idvar = c("variable", "season"),
                   timevar = "variant", direction = "wide")
  coefficients <- bundle$manifest$retained_coefficients
  xfpht <- coefficients$XFPHT
  xfint <- coefficients$XFINT
  fmt <- function(x, digits) formatC(x, format = "f", digits = digits)
  a <- ggplot2::ggplot(curve, ggplot2::aes(photothermal_age, relative_potential_fraction)) +
    ggplot2::geom_segment(ggplot2::aes(x = xfpht, xend = xfpht, y = 0, yend = 1),
      data = curve[1, ], inherit.aes = FALSE, colour = "#ADB5BC", linetype = "dotted", linewidth = .33) +
    ggplot2::geom_line(ggplot2::aes(colour = variant, linetype = variant), linewidth = .61) +
    ggplot2::scale_linetype_manual(values = c(full = "solid", reduced = "dashed"), guide = "none") +
    ggplot2::annotate("text", x = xfpht - 1.6, y = .055, label = fmt(xfpht, 2), hjust = 1,
      family = profile$font_family[[1]], size = 2.45, colour = "#363F46") +
    ggplot2::annotate("text", x = 2.7, y = xfint - .075, label = fmt(xfint, 4), hjust = 0,
      family = profile$font_family[[1]], size = 2.45, colour = "#363F46") +
    scale_variant() +
    ggplot2::guides(colour = ggplot2::guide_legend(override.aes = list(linetype = c("solid", "dashed")))) +
    ggplot2::scale_y_continuous(limits = c(0, 1.06), breaks = seq(0, 1, .25), expand = c(0, 0)) +
    ggplot2::scale_x_continuous(breaks = seq(0, max(curve$photothermal_age), 10), expand = c(0, 0)) +
    ggplot2::labs(x = "累计光温时间（光温日）", y = "相对潜在生殖分配基准", title = "(a)") +
    theme_q1(profile)
  score_axis <- if (metric == "r2") {
    ggplot2::scale_x_continuous(name = "r²", limits = c(0, 1), breaks = seq(0, 1, .2),
      labels = function(x) sprintf("%.1f", x), expand = ggplot2::expansion(add = .015))
  } else {
    ggplot2::scale_x_continuous(name = "NRMSE（%）", limits = c(0, NA), breaks = seq(0, 100, 15),
      expand = ggplot2::expansion(mult = c(0, .085)))
  }
  b <- ggplot2::ggplot(m, ggplot2::aes(score, variable)) +
    ggplot2::geom_segment(data = links, ggplot2::aes(x = score.full, xend = score.reduced,
      y = variable, yend = variable), inherit.aes = FALSE, colour = "#B9C3C9", linewidth = .37) +
    ggplot2::geom_point(data = m[m$variant == "reduced", ], ggplot2::aes(colour = variant),
      shape = 21, fill = "white", size = 2.2, stroke = .43) +
    ggplot2::geom_point(data = m[m$variant == "full", ], ggplot2::aes(colour = variant), shape = 16, size = 1.48) +
    scale_variant() + ggplot2::guides(colour = "none") +
    ggplot2::facet_grid(. ~ season) +
    ggplot2::scale_y_discrete(labels = setNames(labels, variables)) +
    score_axis +
    ggplot2::labs(y = NULL, title = "(b)") +
    theme_q1(profile) + ggplot2::theme(
      strip.background = ggplot2::element_rect(fill = "#EEF2F4", colour = NA),
      strip.text = ggplot2::element_text(colour = "black", margin = ggplot2::margin(t = 4, b = 4)),
      panel.spacing.x = grid::unit(3.6, "mm"),
      panel.grid.major.x = ggplot2::element_line(colour = "#E7ECEF", linewidth = .22),
      axis.ticks.y = ggplot2::element_blank(),
      plot.margin = ggplot2::margin(5.5, 5.5, 5.5, 13))
  plot <- patchwork::wrap_plots(a, b, widths = c(1, 2), guides = "collect") &
    ggplot2::theme(legend.position = "bottom", legend.justification = "center",
      legend.key.spacing.x = grid::unit(7, "mm"),
      plot.title = ggplot2::element_text(face = "bold", size = 8, colour = "black"))
  notes <- if (is_demo) "DEMO · 两批次均待科学审查" else character()
  if (identical(bundle$manifest$growth_scope, "process_excluding_final_25sp")) {
    notes <- c(notes, sprintf("2025 年生长指标剔除 %s 取样", bundle$manifest$excluded_growth_dates[["25SP"]]))
  }
  if (length(notes)) {
    plot <- plot + patchwork::plot_annotation(caption = paste(notes, collapse = "　｜　"),
      theme = ggplot2::theme(plot.caption = ggplot2::element_text(
        family = profile$font_family[[1]], size = 6, hjust = 0, colour = "#53616A")))
  }
  list(plot = plot, source = curve, metrics = metrics, height_mm = 77)
}

# Controlled forward comparison; theoretical potential curve is separate from model states.
build_partition_forward_compact <- function(function_data,metrics,profile,is_demo=FALSE) {
  colours<-c(baseline="#0072B2",disabled="#D55E00")
  scale_variant<-function()ggplot2::scale_colour_manual(values=colours,
    breaks=c("baseline","disabled"),labels=c("动态分配开启","动态分配关闭"),name=NULL)
  a<-ggplot2::ggplot(function_data,ggplot2::aes(photothermal_age,relative_potential_fraction,colour=variant))+
    ggplot2::geom_line(linewidth=line_width_mm(1))+scale_variant()+
    ggplot2::scale_y_continuous(limits=c(0,1.07),breaks=c(0,.25,.5,.75,1),expand=c(0,0))+
    ggplot2::labs(x="开花后累计光温时间（光温日）",y="相对潜在分配基准",title="(a) 潜在分配基准函数")+
    theme_q1(profile)+demo_watermark(is_demo)
  variables<-c("TERMINAL_FRESH","FRESH_CUM","FRESH_INC","SWAD","LWAD","LAID")
  labels<-c("季末鲜果产量","累计采收鲜重","单次采收鲜重","茎干重","叶干重","LAI")
  m<-metrics[metrics$dataset_role=="all" & metrics$date_offset_days==0 &
    metrics$season_id %in% c("25SP","26SP") & metrics$variable %in% variables,]
  m$y<-match(m$variable,variables)+ifelse(m$season_id=="25SP",-.13,.13)
  links<-merge(m[m$variant=="baseline",c("season_id","variable","nrmse_pct","y")],
    m[m$variant=="disabled",c("season_id","variable","nrmse_pct")],by=c("season_id","variable"),suffixes=c("_baseline","_disabled"))
  d<-ggplot2::ggplot(m,ggplot2::aes(nrmse_pct,y,colour=variant,shape=season_id))+
    ggplot2::geom_segment(data=links,ggplot2::aes(x=nrmse_pct_baseline,xend=nrmse_pct_disabled,y=y,yend=y),
      inherit.aes=FALSE,colour="#BDC6CC",linewidth=.4)+
    ggplot2::geom_point(size=1.9)+scale_variant()+
    ggplot2::scale_shape_manual(values=c("25SP"=16,"26SP"=17),name=NULL)+
    ggplot2::scale_y_continuous(breaks=seq_along(variables),labels=labels,limits=c(.5,6.5))+
    ggplot2::scale_x_continuous(limits=c(0,NA),expand=ggplot2::expansion(mult=c(0,.05)))+
    ggplot2::labs(x="nRMSE（%）",y=NULL,title="(d) 固定参数前向对照")+
    theme_q1(profile)+ggplot2::guides(colour="none")
  plot<-patchwork::wrap_plots(a,d,widths=c(1,1.2),guides="collect") & ggplot2::theme(legend.position="bottom",plot.title=ggplot2::element_text(face="plain"))
  plot<-plot+patchwork::plot_annotation(caption="未重新率定：由C31直接设XFINT=1；正式重新率定消融待开展。\n26SP的LAI指标含12个SLA推算值，与原C31口径一致。",
    theme=ggplot2::theme(plot.caption=ggplot2::element_text(family=profile$font_family[[1]],size=5.7,hjust=0)))
  list(plot=plot,source=function_data,metrics=m,height_mm=92)
}

build_partition_ablation <- function(events, function_data, metrics, profile, is_demo = FALSE, smooth = FALSE) {
  colours <- c(baseline = "#0072B2", disabled = "#D55E00")
  labels <- c(baseline = "动态分配开启", disabled = "动态分配关闭")
  scale_variant <- function() ggplot2::scale_colour_manual(values = colours, breaks = names(colours), labels = labels, name = NULL)
  p_a <- ggplot2::ggplot(function_data, ggplot2::aes(x = photothermal_age, y = relative_potential_fraction, colour = variant)) +
    ggplot2::geom_line(linewidth = line_width_mm(1)) + scale_variant() +
    ggplot2::scale_y_continuous(limits = c(0, 1.06), breaks = c(0, .25, .5, .75, 1), expand = c(0, 0)) +
    ggplot2::labs(x = "开花后累计光温时间（光温日）", y = "相对潜在分配基准", title = "(a) 潜在分配上限的参数化函数") +
    theme_q1(profile) + ggplot2::theme(legend.position = "bottom") + demo_watermark(is_demo)
  source <- events
  if (smooth) {
    groups <- split(events, list(events$season_id, events$variant), drop = TRUE)
    source <- do.call(rbind, lapply(groups, function(d) {
      d <- d[order(d$dap), ]
      if (any(diff(d$simulated) < -1e-9)) stop("Cumulative ablation nodes decrease")
      x <- sort(unique(c(d$dap, seq(min(d$dap), max(d$dap), length.out = 240))))
      y <- stats::splinefun(d$dap, d$simulated, method = "monoH.FC")(x)
      if (any(diff(y) < -1e-8)) stop("Monotone visual interpolation decreased")
      data.frame(season_id = d$season_id[1], variant = d$variant[1], dap = x, simulated = y)
    }))
  }
  event_panel <- function(season, title) {
    d <- source[source$season_id == season, ]
    obs <- events[events$season_id == season & events$variant == "baseline", ]
    ggplot2::ggplot(d, ggplot2::aes(x = dap, y = simulated, colour = variant)) +
      ggplot2::geom_line(linewidth = line_width_mm(1)) +
      ggplot2::geom_point(data = obs, ggplot2::aes(x = dap, y = observed), inherit.aes = FALSE,
        colour = "#202020", fill = "white", shape = 21, size = 1.8, stroke = .5) +
      scale_variant() +
      ggplot2::scale_y_continuous(limits = c(0, NA), expand = ggplot2::expansion(mult = c(0, .08))) +
      ggplot2::labs(x = "定植后天数（d）", y = expression("累计采收鲜重（t " * ha^{-1} * "）"), title = title) +
      theme_q1(profile) + ggplot2::theme(legend.position = "bottom")
  }
  p_b <- event_panel("25SP", "(b) 2025年春 W3N3")
  p_c <- event_panel("26SP", "(c) 2026年春 W3N3")
  variables <- c("TERMINAL_FRESH", "FRESH_CUM", "FRESH_INC", "SWAD", "LWAD", "LAID")
  variable_labels <- c("季末鲜果产量", "累计采收鲜重", "单次采收鲜重", "茎干重", "叶干重", "LAI")
  m <- metrics[metrics$dataset_role == "all" & metrics$date_offset_days == 0 &
    metrics$season_id %in% c("25SP", "26SP") & metrics$variable %in% variables, ]
  m$y <- match(m$variable, variables) + ifelse(m$season_id == "25SP", -.14, .14)
  lo <- m[m$variant == "baseline", c("season_id", "variable", "nrmse_pct", "y")]
  hi <- m[m$variant == "disabled", c("season_id", "variable", "nrmse_pct")]
  links <- merge(lo, hi, by = c("season_id", "variable"), suffixes = c("_baseline", "_disabled"))
  p_d <- ggplot2::ggplot(m, ggplot2::aes(x = nrmse_pct, y = y, colour = variant, shape = season_id)) +
    ggplot2::geom_segment(data = links, ggplot2::aes(x = nrmse_pct_baseline, xend = nrmse_pct_disabled, y = y, yend = y),
      inherit.aes = FALSE, colour = "#B9C3C9", linewidth = line_width_mm(.8)) +
    ggplot2::geom_point(size = 1.8, stroke = .5) + scale_variant() +
    ggplot2::scale_shape_manual(values = c("25SP" = 16, "26SP" = 17), labels = c("2025年春", "2026年春"), name = NULL) +
    ggplot2::scale_y_continuous(breaks = seq_along(variables), labels = variable_labels, limits = c(.5, 6.5)) +
    ggplot2::scale_x_continuous(limits = c(0, NA), expand = ggplot2::expansion(mult = c(0, .05))) +
    ggplot2::labs(x = "nRMSE（%）", y = NULL, title = "(d) 全处理误差及变量间权衡") +
    theme_q1(profile) + ggplot2::theme(legend.position = "bottom", legend.box = "vertical") +
    ggplot2::guides(colour = "none")
  combined <- patchwork::wrap_plots(p_a, p_b, p_c, p_d, ncol = 2, guides = "collect") &
    ggplot2::theme(legend.position = "bottom", plot.title = ggplot2::element_text(size = 7, face = "bold"))
  combined <- combined + patchwork::plot_annotation(caption = if (smooth)
    "样板｜累计线为单调视觉插值，不进入指标；固定参数前向对照，未重新率定。" else
    "样板｜黑边点为观测；累计线连接真实采收节点；同日工作口径，固定参数前向对照。",
    theme = ggplot2::theme(plot.caption = ggplot2::element_text(family = profile$font_family[[1]], size = 5.7, hjust = 0)))
  list(plot = combined, source = source, metrics = m, function_source = function_data, height_mm = 160)
}
