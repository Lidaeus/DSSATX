build_growth_dynamics <- function(comparison,trajectory,selection,profile,is_demo=FALSE) {
  keys<-paste(selection$season_id,selection$treatment)
  obs<-comparison[comparison$variable %in% c("LAID","LWAD","SWAD") & paste(comparison$season_id,comparison$treatment) %in% keys,]
  daily<-trajectory[paste(trajectory$season_id,trajectory$treatment) %in% keys,]
  meta<-selection[,c("season_id","treatment","water_level","nitrogen_level")]
  obs<-merge(obs,meta,by=c("season_id","treatment"))
  variables<-c("LAID","LWAD","SWAD");labels<-c("LAI（m² m⁻²）","叶干重（kg ha⁻¹）","茎干重（kg ha⁻¹）")
  panels<-list()
  for(season in c("25SP","26SP")) for(i in seq_along(variables)) {
    v<-variables[i];a<-daily[daily$season_id==season & daily$variable==v,]
    o<-obs[obs$season_id==season & obs$variable==v,]
    limit_data<-obs[obs$variable==v,];s<-limit_data$observed_se;s[is.na(s)]<-0
    ylim<-c(0,max(c(daily$simulated[daily$variable==v],limit_data$observed+s))*1.08)
    p<-ggplot2::ggplot()+
      ggplot2::geom_line(data=a,ggplot2::aes(dap,simulated,colour=nitrogen_level,group=treatment),linewidth=line_width_mm(1))+
      ggplot2::geom_errorbar(data=o[!is.na(o$observed_se),],ggplot2::aes(dap,ymin=pmax(0,observed-observed_se),
        ymax=observed+observed_se,colour=nitrogen_level),width=1.2,linewidth=.25)+
      ggplot2::geom_point(data=o,ggplot2::aes(dap,observed,fill=nitrogen_level,shape=water_level),
        colour="#202020",size=1.8,stroke=.4)+
      ggplot2::geom_point(data=o[o$observation_origin=="SLA_ratio_derived",],ggplot2::aes(dap,observed),
        shape=4,colour="#202020",size=2.1,stroke=.45)+
      ggplot2::scale_colour_manual(values=unlist(profile$nitrogen_colors),name=NULL)+
      ggplot2::scale_fill_manual(values=unlist(profile$nitrogen_colors),name=NULL)+
      ggplot2::scale_shape_manual(values=unlist(profile$water_shapes),name=NULL)+
      ggplot2::scale_x_continuous(limits=c(-1.5,126),breaks=c(0,40,80,120),expand=c(0,0))+
      ggplot2::scale_y_continuous(limits=ylim,expand=c(0,0))+
      ggplot2::labs(x="定植后天数（d）",y=labels[i],title=paste0("(",letters[length(panels)+1],") ",season))+theme_q1(profile)+
      ggplot2::theme(legend.position="bottom",plot.title=ggplot2::element_text(face="plain"))
    if(!length(panels))p<-p+demo_watermark(is_demo)
    panels[[length(panels)+1]]<-p
  }
  plot<-patchwork::wrap_plots(panels,ncol=3,guides="collect") & ggplot2::theme(legend.position="bottom")
  plot<-plot+patchwork::plot_annotation(caption="日模拟线与观测点；×为SLA推算LAI，无实测SE。\n误差棒仅为可追溯重复的SE；两春均选W3N3、W1N0及留出W1N1。",
    theme=ggplot2::theme(plot.caption=ggplot2::element_text(family=profile$font_family[[1]],size=5.7,hjust=0)))
  list(plot=plot,source=obs,daily=daily,selection=selection,height_mm=145)
}

build_spring_growth <- function(comparison, trajectory, selection, profile, treatment_order, status_note) {
  variables <- c("LAID", "LWAD")
  labels <- c("LAI（m² m⁻²）", "叶干重（kg ha⁻¹）")
  key <- function(d) paste(d$season_id, d$treatment)
  obs <- comparison[comparison$variable %in% variables & key(comparison) %in% key(selection), ]
  daily <- trajectory[trajectory$variable %in% variables & key(trajectory) %in% key(selection), ]
  stopifnot(nrow(obs) > 0, nrow(daily) > 0)
  scales <- spring_management_scales(selection, profile, treatment_order)
  years <- c("26SP" = "2026年", "25SP" = "2025年")
  xlim <- c(0, max(daily$dap, obs$dap) + 2)
  panels <- list()
  for (season in names(years)) for (i in seq_along(variables)) {
    v <- variables[i]
    d <- daily[daily$season_id == season & daily$variable == v, ]
    o <- obs[obs$season_id == season & obs$variable == v, ]
    e <- o[is.finite(o$observed_se), ]
    stopifnot(setequal(d$management, treatment_order), setequal(o$management, treatment_order))
    qq <- obs[obs$variable == v, ]
    limit <- 1.09 * max(daily$simulated[daily$variable == v], qq$observed,
                        qq$observed + qq$observed_se, na.rm = TRUE)
    title <- paste0("(", letters[length(panels) + 1L], ") ", years[[season]])
    panels[[length(panels) + 1L]] <- ggplot2::ggplot() +
      ggplot2::geom_line(data = d, ggplot2::aes(dap, simulated, colour = management, group = management),
        linewidth = .42, show.legend = FALSE) +
      ggplot2::geom_errorbar(data = e, ggplot2::aes(dap, ymin = pmax(0, observed - observed_se),
        ymax = observed + observed_se, colour = management), width = 1.9, linewidth = .27,
        show.legend = FALSE) +
      ggplot2::geom_point(data = o, ggplot2::aes(dap, observed, fill = management),
        shape = 21, size = 1.55, colour = "#2C2C2C", stroke = .35) +
      ggplot2::scale_colour_manual(values = scales$colors) +
      ggplot2::scale_fill_manual(values = scales$colors, breaks = treatment_order, name = NULL) +
      ggplot2::scale_x_continuous(breaks = seq(0, 120, 40)) +
      ggplot2::scale_y_continuous(breaks = scales::breaks_pretty(n = 4)) +
      ggplot2::coord_cartesian(xlim = xlim, ylim = c(0, limit), expand = FALSE) +
      ggplot2::labs(x = "定植后天数（d）", y = labels[i], title = title) +
      theme_q1(profile) + ggplot2::theme(
        plot.title = ggplot2::element_text(size = profile$panel_label_size_pt),
        panel.grid.major = ggplot2::element_line(colour = "#E9EDF0", linewidth = .19))
  }
  note <- paste(c("实线为逐日模拟，圆点为实测均值，误差棒表示 ±1 SE。", status_note), collapse = "\n")
  plot <- patchwork::wrap_plots(panels, ncol = 4, guides = "collect", axis_titles = "collect_x") +
    patchwork::plot_annotation(caption = note, theme = spring_caption_theme(profile))
  plot <- plot & ggplot2::theme(legend.position = "bottom", legend.justification = "center")
  list(plot = plot, source = obs, daily = daily, selection = selection, height_mm = 76)
}
