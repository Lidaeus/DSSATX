build_sensitivity_update <- function(scores,intervals,profile,is_demo=FALSE) {
  groups<-c("phenology","canopy","biomass","yield_harvest","water_response","nitrogen_response","water_nitrogen_interaction")
  group_labels<-c("物候","冠层","生物量","采收","水响应","氮响应","水氮交互")
  importance<-stats::aggregate(group_score~parameter,scores,mean)
  selected<-head(importance$parameter[order(importance$group_score,decreasing=TRUE)],12)
  d<-scores[scores$parameter %in% selected,]
  d$parameter<-factor(d$parameter,levels=rev(selected))
  d$group<-factor(d$response_group,levels=groups,labels=group_labels)
  d$season_id<-factor(d$season_id,levels=c("25SP","26SP"))
  a<-ggplot2::ggplot(d,ggplot2::aes(group,parameter,fill=group_score))+
    ggplot2::geom_tile(colour="white",linewidth=.2)+ggplot2::facet_grid(~season_id)+
    ggplot2::scale_fill_gradient(low="#F4F6F7",high="#185E88",name="归一化份额")+
    ggplot2::labs(x=NULL,y=NULL,title="(a) 历史筛选域的过程敏感性")+theme_q1(profile)+
    ggplot2::theme(axis.line=ggplot2::element_blank(),axis.ticks=ggplot2::element_blank(),
      axis.text.x=ggplot2::element_text(angle=90,hjust=1,vjust=.5,size=6.6),
      strip.background=ggplot2::element_rect(fill="#EEF1F3",colour=NA),legend.position="bottom")+
    ggplot2::guides(fill=ggplot2::guide_colourbar(barwidth=grid::unit(30,"mm"),barheight=grid::unit(2,"mm")))+
    demo_watermark(is_demo)
  params<-c("EM-FL","TB1","TRIFL","SLAVR","FL-SD","PODUR","XFRT","XMAGE")
  z<-intervals[intervals$parameter %in% params,]
  z$y<-match(z$parameter,rev(params))+ifelse(z$phase=="initial",.13,-.13)
  for(column in c("q025","median","q975")) z[[paste0(column,"_relative")]]<-
    (z[[column]]-z$working_lower)/(z$working_upper-z$working_lower)
  b<-ggplot2::ggplot(z,ggplot2::aes(y=y,colour=phase))+
    ggplot2::geom_segment(ggplot2::aes(x=q025_relative,xend=q975_relative,yend=y),linewidth=.9)+
    ggplot2::geom_point(ggplot2::aes(x=median_relative),size=1.8)+
    ggplot2::scale_colour_manual(values=c(initial="#A9AFB5",final="#0072B2"),
      breaks=c("initial","final"),labels=c("初始 n=199","最终 n=141"),name=NULL)+
    ggplot2::scale_y_continuous(breaks=seq_along(params),labels=rev(params),limits=c(.5,length(params)+.5))+
    ggplot2::scale_x_continuous(limits=c(-.03,1.03),breaks=c(0,.5,1),expand=c(0,0))+
    ggplot2::labs(x="实际PST工作域内的相对位置",y=NULL,title="(b) 参考IES集合更新")+
    theme_q1(profile)+ggplot2::theme(legend.position="bottom")
  plot<-patchwork::wrap_plots(a,b,widths=c(1.55,1))+patchwork::plot_annotation(
    caption="各过程内归一化；历史双春筛选不等于C31局部敏感性。区间为2.5%–97.5%分位数，排除base。",
    theme=ggplot2::theme(plot.caption=ggplot2::element_text(family=profile$font_family[[1]],size=5.7,hjust=0)))
  list(plot=plot,source=d,intervals=z,height_mm=123)
}

build_stage2_density <- function(samples,intervals,profile,is_demo=FALSE) {
  parameters<-setdiff(unique(samples$parameter),"TRIFL")
  d<-samples[samples$phase=="final" & samples$parameter %in% parameters,]
  d$parameter<-factor(d$parameter,levels=parameters)
  initial<-intervals[intervals$phase=="initial" & intervals$parameter %in% parameters,]
  final<-intervals[intervals$phase=="final" & intervals$parameter %in% parameters,]
  initial$parameter<-factor(initial$parameter,levels=parameters);final$parameter<-factor(final$parameter,levels=parameters)
  plot<-ggplot2::ggplot(d,ggplot2::aes(value))+
    ggplot2::geom_rect(data=initial,ggplot2::aes(xmin=q025,xmax=q975,ymin=-Inf,ymax=Inf),inherit.aes=FALSE,fill="#EEF1F3")+
    ggplot2::geom_density(ggplot2::aes(y=ggplot2::after_stat(scaled)),fill="#70A9CC",colour="#205B7C",alpha=.65,linewidth=.4)+
    ggplot2::geom_vline(data=initial,ggplot2::aes(xintercept=median),colour="#7C858B",linetype="dotted",linewidth=.35)+
    ggplot2::geom_vline(data=final,ggplot2::aes(xintercept=median),colour="#AC3A31",linewidth=.4)+
    ggplot2::facet_wrap(~parameter,scales="free",ncol=4)+
    ggplot2::labs(x="参数值",y="相对密度",caption="参考IES集合：初始199、最终141个非base成员。灰带为初始2.5%–97.5%区间；红线为最终中位数。")+
    theme_q1(profile)+ggplot2::theme(strip.background=ggplot2::element_rect(fill="#EEF1F3",colour=NA),
      strip.text=ggplot2::element_text(face="plain"),axis.text.y=ggplot2::element_blank(),axis.ticks.y=ggplot2::element_blank(),
      panel.spacing=grid::unit(3,"mm"),plot.caption=ggplot2::element_text(size=5.7,hjust=0))+
    demo_watermark(is_demo)
  list(plot=plot,source=d,intervals=intervals[intervals$parameter %in% parameters,],height_mm=158)
}
