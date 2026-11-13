# Scientific diagnostics use R and only hash-frozen tabular evidence.
args <- commandArgs(trailingOnly=TRUE)
out <- normalizePath(args[[1]],winslash='/',mustWork=TRUE)
if(.Platform$OS.type=='windows')Sys.setlocale('LC_CTYPE','English_United States.utf8')
source('D:/Tomato_Cal/paper/R/common.R',encoding='UTF-8')
check_r_dependencies()
man <- jsonlite::fromJSON(file.path(out,'data_manifest.json'),simplifyVector=FALSE)
stopifnot(identical(man$data_status,'actual_deterministic_diagnostic'))
for(a in man$artifacts)stopifnot(identical(tolower(sha256_file(file.path(out,a$path))),tolower(a$sha256)))
q <- read.csv(file.path(out,'daily_leafN.csv'),check.names=FALSE)
obs <- read.csv(file.path(out,'comparison.csv'),check.names=FALSE)
obs <- obs[obs$variable=='LEAF_N_PCT',]
metadata <- unique(q[,c('model','season_id','trno','treatment_label','water_level','nitrogen_level')])
stopifnot(!anyDuplicated(metadata[,c('model','season_id','trno')]))
obs <- merge(obs,metadata,by=c('model','season_id','trno'),all.x=TRUE)
obs$dap <- as.numeric(as.Date(obs$date)-as.Date(ifelse(obs$season_id=='26SP','2026-03-14','2025-03-16')))
stopifnot(!anyNA(obs$water_level),!anyNA(obs$nitrogen_level))
profile <- load_publication_profile('D:/Tomato_Cal/configs/figures/publication.json')
for(n in c('water_level','nitrogen_level','season_id','model')){q[[n]] <- as.character(q[[n]]);obs[[n]] <- as.character(obs[[n]])}
models <- unique(q$model)
q$model <- factor(q$model,levels=models);obs$model <- factor(obs$model,levels=models)
q$season_id <- factor(q$season_id,levels=c('26SP','25SP'));obs$season_id <- factor(obs$season_id,levels=c('26SP','25SP'))
q$water_level <- factor(q$water_level,levels=c('W3','W2','W1'));obs$water_level <- factor(obs$water_level,levels=c('W3','W2','W1'))
plot_leaf <- function(data,points,title){
  ggplot2::ggplot(data,ggplot2::aes(dap,leaf_n_pct,colour=nitrogen_level,group=interaction(model,season_id,trno)))+
    ggplot2::geom_line(linewidth=.3)+
    ggplot2::geom_point(data=points,ggplot2::aes(dap,observed,fill=nitrogen_level,shape=water_level,group=interaction(model,season_id,trno)),colour='#222222',size=1.3,stroke=.3,inherit.aes=FALSE)+
    ggplot2::facet_grid(model~season_id+water_level,scales='fixed',space='fixed')+
    ggplot2::scale_colour_manual(values=unlist(profile$nitrogen_colors),name='Nitrogen')+
    ggplot2::scale_fill_manual(values=unlist(profile$nitrogen_colors),name='Nitrogen')+
    ggplot2::scale_shape_manual(values=unlist(profile$water_shapes),name='Water')+
    ggplot2::labs(title=title,x='Days after planting (DAP)',y='Leaf N (% dry mass)',caption='Actual deterministic calibration diagnostics; daily lines without smoothing. No independent validation.\nLocal curve shape was not an acceptance criterion. 25SP has no W2 treatment.')+
    theme_q1(profile)+ggplot2::theme(strip.text=ggplot2::element_text(size=5.1),legend.position='bottom',plot.caption=ggplot2::element_text(size=5),plot.title=ggplot2::element_text(size=8))
}
plots <- list(diagnostic_best_leafN_full=plot_leaf(q,obs,'Preserved baseline and independently replayed calibrated candidates'),diagnostic_best_leafN_zoom=plot_leaf(q[q$dap>=15 & q$dap<=70,],obs[obs$dap>=15 & obs$dap<=70,],'Early leaf N comparison (no monotonicity constraint)'))
for(name in names(plots)){
  ggplot2::ggsave(file.path(out,paste0(name,'.png')),plots[[name]],width=183,height=160,units='mm',dpi=600,bg='white')
  ggplot2::ggsave(file.path(out,paste0(name,'.pdf')),plots[[name]],width=183,height=160,units='mm',device=grDevices::cairo_pdf)
  ggplot2::ggsave(file.path(out,paste0(name,'.svg')),plots[[name]],width=183,height=160,units='mm',device=svglite::svglite)
}
files <- list.files(out,pattern='^diagnostic_.*[.](png|pdf|svg)$',full.names=TRUE)
jsonlite::write_json(list(data_manifest_sha256=sha256_file(file.path(out,'data_manifest.json')),R=R.version.string,profile_sha256=sha256_file('D:/Tomato_Cal/configs/figures/publication.json'),artifacts=lapply(files,function(f)list(path=basename(f),sha256=sha256_file(f)))),file.path(out,'figure_manifest.json'),auto_unbox=TRUE,pretty=TRUE)
