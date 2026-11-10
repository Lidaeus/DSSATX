# Split mixed labels into explicit font runs so CJK fallback cannot select
# an unrelated UI font. Kept at the export boundary; data and geometry unchanged.
publication_font_runs <- function(label) {
  chars <- strsplit(enc2utf8(label), "", fixed=TRUE)[[1]]
  if (!length(chars)) return(list())
  cjk <- grepl("[\u2e80-\u9fff\uf900-\ufaff\uff01-\uff60\u3000-\u303f]", chars, perl=TRUE)
  groups <- cumsum(c(TRUE,diff(cjk)!=0))
  lapply(split(seq_along(chars),groups),function(i) list(text=paste(chars[i],collapse=""),
    family=if(cjk[i[1]]) "SimSun" else "Times New Roman"))
}

makeContent.publication_mixed_text <- function(x) {
  original <- x$original
  labels <- as.character(original$label)
  get_index <- function(v,i,default) if(is.null(v)||!length(v)) default else v[(i-1)%%length(v)+1]
  children <- list()
  for (i in seq_along(labels)) {
    if(is.na(labels[i])||!nzchar(labels[i])) next
    gp <- as.list(original$gp)
    for (key in names(gp)) if(length(gp[[key]])>1) gp[[key]] <- get_index(gp[[key]],i,NULL)
    font_size <- if(is.null(gp$fontsize)) 12 else gp$fontsize
    line_height <- if(is.null(gp$lineheight)) 1.2 else gp$lineheight
    hjust <- get_index(original$hjust,i,.5);vjust <- get_index(original$vjust,i,.5)
    if(!is.finite(hjust)) hjust <- .5
    if(!is.finite(vjust)) vjust <- .5
    lines <- strsplit(labels[i],"\n",fixed=TRUE)[[1]]
    line_children <- list()
    for (j in seq_along(lines)) {
      runs <- publication_font_runs(lines[j])
      run_grobs <- lapply(runs,function(run) {
        run_gp <- gp;run_gp$fontfamily <- run$family
        grid::textGrob(run$text,x=0,y=0,just=c("left","centre"),gp=do.call(grid::gpar,run_gp))
      })
      if(!length(run_grobs)) next
      widths <- lapply(run_grobs,grid::grobWidth)
      total <- Reduce(`+`,widths)
      offset <- -hjust*total
      for(k in seq_along(run_grobs)) {
        child <- run_grobs[[k]]
        child$x <- offset
        child$y <- grid::unit((length(lines)-j+.5-length(lines)*vjust)*font_size*line_height,"points")
        line_children[[length(line_children)+1]] <- child
        offset <- offset+widths[[k]]
      }
    }
    children[[length(children)+1]] <- grid::gTree(children=do.call(grid::gList,line_children),
      vp=grid::viewport(x=get_index(original$x,i,grid::unit(.5,"npc")),
        y=get_index(original$y,i,grid::unit(.5,"npc")),width=grid::unit(0,"mm"),height=grid::unit(0,"mm"),
        angle=get_index(original$rot,i,0),clip="off"))
  }
  grid::setChildren(x,do.call(grid::gList,children))
}

publication_mixed_fonts <- function(grob) {
  if(inherits(grob,"text") && is.character(grob$label) &&
     any(grepl("[\u2e80-\u9fff\uf900-\ufaff\uff01-\uff60\u3000-\u303f]",grob$label,perl=TRUE),na.rm=TRUE)) {
    return(grid::gTree(original=grob,cl="publication_mixed_text",name=grob$name,vp=grob$vp))
  }
  if(!is.null(grob$children)) grob$children <- do.call(grid::gList,lapply(grob$children,publication_mixed_fonts))
  if(!is.null(grob$grobs)) grob$grobs <- lapply(grob$grobs,publication_mixed_fonts)
  grob
}

publication_plot_grob <- function(plot) {
  if(.Platform$OS.type=="windows") grDevices::windowsFonts(
    "Times New Roman"=grDevices::windowsFont("Times New Roman"),
    "SimSun"=grDevices::windowsFont("SimSun"))
  grob <- if(inherits(plot,"patchwork")) patchwork::patchworkGrob(plot) else ggplot2::ggplotGrob(plot)
  publication_mixed_fonts(grob)
}
