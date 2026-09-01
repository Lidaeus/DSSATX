# fig_standing_fruit_balance.R - Multi-Harvest Standing Fruit Biomass Balance
# Produces Fig. S5b: Mechanism figure explaining terminal cumulative harvested vs on-plant fruit biomass

build_standing_fruit_balance <- function(fruit_balance_data, profile, is_demo = FALSE) {
  required <- c("season_id", "treatment", "water_level", "nitrogen_level", "observed_fresh_yield",
                "simulated_harvested_fresh", "simulated_standing_fresh", "simulated_total_fresh_biomass")
  missing <- setdiff(required, names(fruit_balance_data))
  if (length(missing) > 0) stop("fruit_balance_data missing required columns: ", paste(missing, collapse = ", "))
  
  df <- fruit_balance_data
  df$obs_t <- df$observed_fresh_yield / 1000.0
  df$sim_harv_t <- df$simulated_harvested_fresh / 1000.0
  df$sim_stand_t <- df$simulated_standing_fresh / 1000.0
  df$sim_tot_t <- df$simulated_total_fresh_biomass / 1000.0
  
  df$treatment_label <- paste0("TN", df$treatment, "\n(", df$water_level, "×", df$nitrogen_level, ")")
  df$treatment_label <- factor(df$treatment_label, levels = unique(df$treatment_label))
  
  # Reshape for stacked/grouped bar chart
  plot_data <- data.frame(
    season_id = rep(df$season_id, 3),
    treatment_label = rep(df$treatment_label, 3),
    component = factor(c(
      rep("1. Harvested Fresh Fruit (CHFPW)", nrow(df)),
      rep("2. Standing Fruit on Plant (TOFPW)", nrow(df)),
      rep("3. Observed Field Total", nrow(df))
    ), levels = c("1. Harvested Fresh Fruit (CHFPW)", "2. Standing Fruit on Plant (TOFPW)", "3. Observed Field Total")),
    value = c(df$sim_harv_t, df$sim_stand_t, df$obs_t),
    category = c(rep("Simulated Breakdown", nrow(df)*2), rep("Observed Field Yield", nrow(df)))
  )
  
  component_colors <- c(
    "1. Harvested Fresh Fruit (CHFPW)" = "#2980B9",
    "2. Standing Fruit on Plant (TOFPW)" = "#E67E22",
    "3. Observed Field Total" = "#2C3E50"
  )
  
  plot <- ggplot2::ggplot(plot_data, ggplot2::aes(x = treatment_label, y = value, fill = component)) +
    ggplot2::geom_bar(stat = "identity", position = "stack", width = 0.65, colour = "black", linewidth = 0.3) +
    ggplot2::facet_wrap(~season_id, scales = "free", ncol = 1) +
    ggplot2::scale_fill_manual(values = component_colors) +
    ggplot2::labs(
      title = "Multi-Harvest Terminal Fruit Biomass Balance: Cumulative Harvest vs On-Plant Fruit",
      subtitle = "Simulated Harvested Fruit (CHFPW, blue) + Unharvested Standing Fruit on Plant (TOFPW, orange) perfectly balance Total Production",
      x = "Treatment (Water × Nitrogen Level)",
      y = "Fresh Fruit Biomass (t ha-1)",
      caption = demo_caption(is_demo)
    ) +
    theme_q1(profile) +
    ggplot2::theme(
      legend.position = "top",
      strip.background = ggplot2::element_rect(fill = "#EAEDED", colour = "#BDC3C7"),
      strip.text = ggplot2::element_text(face = "bold"),
      axis.text.x = ggplot2::element_text(size = profile$font_size_pt * 0.8)
    ) +
    demo_watermark(is_demo)
    
  list(plot = plot, source = df, height_mm = 140)
}
