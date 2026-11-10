"""Editable three-table document from frozen stage-2 CSVs; bundled Python only."""
from pathlib import Path
import csv
import json
import math
from docx import Document
from docx.shared import Mm, Pt, RGBColor
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'workspace/reviews/paper_stage2_20261031'
B=OUT/'paper_data'
TABLES=OUT/'tables'

def read(name):
    with (B/name).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def fmt(value,digits=6):
    try:
        v=float(value)
        return f'{v:.{digits}g}' if math.isfinite(v) else '—'
    except (ValueError,TypeError):return '—'
def fonts(run,size=9.5,bold=False):
    run.font.name='Times New Roman';run.font.size=Pt(size);run.bold=bold;run.font.color.rgb=RGBColor(0,0,0)
    rf=run._element.get_or_add_rPr().get_or_add_rFonts()
    for key,value in [('ascii','Times New Roman'),('hAnsi','Times New Roman'),('eastAsia','宋体'),('cs','Times New Roman')]:rf.set(qn('w:'+key),value)
def para(doc,text,style=None,size=9.5,bold=False):
    p=doc.add_paragraph(style=style);p.paragraph_format.space_after=Pt(4);p.paragraph_format.space_before=Pt(0)
    p.paragraph_format.line_spacing=1.12
    fonts(p.add_run(text),size,bold);return p
def make_table(doc,headers,rows,widths,size=9.5,left_columns=()):
    t=doc.add_table(rows=1,cols=len(headers));t.alignment=WD_TABLE_ALIGNMENT.CENTER;t.autofit=False
    pr=t._tbl.tblPr
    borders=OxmlElement('w:tblBorders')
    for edge in ['top','left','bottom','right','insideH','insideV']:
        e=OxmlElement('w:'+edge);e.set(qn('w:val'),'single');e.set(qn('w:sz'),'4');e.set(qn('w:color'),'D9D9D9');borders.append(e)
    pr.append(borders)
    for col,width in zip(t.columns,widths):col.width=Mm(width)
    def fill_row(row,values,header=False):
        props=row._tr.get_or_add_trPr();cant=OxmlElement('w:cantSplit');props.append(cant)
        if header:
            repeat=OxmlElement('w:tblHeader');props.append(repeat)
        for i,(cell,text) in enumerate(zip(row.cells,values)):
            cell.width=Mm(widths[i]);cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
            cp=cell._tc.get_or_add_tcPr();margins=OxmlElement('w:tcMar')
            for side,twips in [('top',34),('bottom',34),('left',55),('right',55)]:
                e=OxmlElement('w:'+side);e.set(qn('w:w'),str(twips));e.set(qn('w:type'),'dxa');margins.append(e)
            cp.append(margins)
            if header:
                sh=OxmlElement('w:shd');sh.set(qn('w:fill'),'EDF0F2');cp.append(sh)
            p=cell.paragraphs[0];p.paragraph_format.space_before=Pt(0);p.paragraph_format.space_after=Pt(0);p.paragraph_format.line_spacing=1.04
            p.alignment=WD_ALIGN_PARAGRAPH.LEFT if i in left_columns else WD_ALIGN_PARAGRAPH.CENTER
            fonts(p.add_run(str(text)),size,header)
    fill_row(t.rows[0],headers,True)
    for row in rows:fill_row(t.add_row(),row)
    doc.add_paragraph().paragraph_format.space_after=Pt(0)
    return t
def display_csv(name,headers,rows):
    with (TABLES/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(headers);w.writerows(rows)


def main():
    TABLES.mkdir(exist_ok=True)
    d=Document();s=d.sections[0];s.orientation=WD_ORIENT.LANDSCAPE;s.page_width=Mm(297);s.page_height=Mm(210)
    s.top_margin=s.bottom_margin=Mm(12);s.left_margin=s.right_margin=Mm(15);s.header_distance=s.footer_distance=Mm(6)
    for name in ['Normal','Title','Heading 1','Heading 2','Caption']:
        st=d.styles[name];st.font.name='Times New Roman';st.font.color.rgb=RGBColor(0,0,0)
        rf=st.element.get_or_add_rPr().get_or_add_rFonts();rf.set(qn('w:eastAsia'),'宋体');rf.set(qn('w:ascii'),'Times New Roman');rf.set(qn('w:hAnsi'),'Times New Roman')
    for border in list(d.styles.element.iter(qn('w:pBdr'))):border.getparent().remove(border)
    d.styles['Normal'].font.size=Pt(9.5)
    d.core_properties.title='C31两春图表阶段2主表';d.core_properties.subject='试验设计 关键参数 模拟性能';d.core_properties.author=''
    footer=s.footer.paragraphs[0];footer.alignment=WD_ALIGN_PARAGRAPH.RIGHT
    r=footer.add_run();fonts(r,8);field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');r._r.addnext(field)
    para(d,'C31两春图表阶段2主表',style='Title',size=15)
    para(d,'使用C31确定性参数与同日评价口径。参数参考集合采用141个非base成员，和C31候选分列。以下表格可编辑并可复制到稿件；原10.6版Word未修改。',size=9.5)
    tab1=read('Table1_trial_design.csv')
    headers=['季节','水氮处理','TN','Ep比例','总灌水量\nmm','总施氮量\nkg N ha⁻¹','角色','LAI/叶/茎\nn','累计/单次采收\nn']
    rows=[]
    for r in tab1:
        design='CK' if r['water_level']=='CK' else r['water_level']+r['nitrogen_level']
        rows.append([r['season_id'],design,r['treatment'],fmt(r['ep_ratio']),f"{float(r['irrigation_mm']):.1f}",
            f"{float(r['nitrogen_kg_ha']):.0f}",r['evaluation_label_zh'].replace('处理',''),
            r['LAID_n']+('*' if int(r['derived_LAI_n']) else '')+'/'+r['LWAD_n']+'/'+r['SWAD_n'],r['FRESH_CUM_n']+'/'+r['FRESH_INC_n']])
    para(d,'表1 两春试验处理及评价数据范围',size=12,bold=True)
    make_table(d,headers,rows,[17,24,12,22,31,34,24,45,49],size=9.2)
    para(d,'注：管理量为C31实际FileX配置，尚需与田间记录对照。W1/W2/W3为0.4/0.8/1.2 Ep；CK单列。每处理有1个季末评价点。n不是田间重复数；*表示4个LAI节点中有1个为SLA关系推算值（26SP DAP105），指标保留原C31全节点口径。',size=8.5)
    display_csv('Table1_试验设计_排版版.csv',headers,rows)
    tab2=read('Table2_key_parameters.csv')
    h2=['过程','参数','含义','单位','文件','原模板值','实际PST工作域','C31候选值','状态']
    r2=[]
    for r in tab2:
        fixed=r['fixed_in_reference_ies'].lower()=='true'
        domain='固定' if fixed else '['+fmt(r['working_lower'])+', '+fmt(r['working_upper'])+']'
        r2.append([r['process'],r['parameter'],r['definition_zh'],r['unit'],r['frozen_location'],'—',domain,fmt(r['c31_candidate_value']),'固定' if fixed else '活动'])
    display_csv('Table2_关键参数_排版版.csv',h2,r2)
    for page,part in enumerate([r2],1):
        d.add_page_break();para(d,'表2 关键模型参数及C31确定性参数化结果'+(' 续表' if page==2 else ''),size=13,bold=True)
        para(d,'实际PST工作域来自09/27参考IES控制文件；C31候选值保留参数CSV精度。',size=9.5)
        make_table(d,h2,part,[18,22,58,32,14,18,43,26,17],size=9.2,left_columns=(2,))
        para(d,'注：原番茄默认值尚未核实，统一记为“—”，不能据此计算参数变化百分比。固定/活动均指09/27参考IES状态。模型实际可读XMAGE=13.4、XFPHT=43.7、XFINT=0.3799。XFINT与XFPHT在本轮固定，不绘本轮后验分布或相关。',size=9)
        para(d,'LFMAX标准条件为30 °C、350 vpm CO₂及高光照。SENDAY为水分胁迫致衰系数；THRSH为种子占种子加果壳总干重的最大百分比。用于茄子时保留CROPGRO模板的种子/果壳结构含义。',size=8.5)
    tab3=read('Table3_model_performance.csv')
    labels={'LAID':('LAI','m² m⁻²'),'LWAD':('叶干重','kg ha⁻¹'),'SWAD':('茎干重','kg ha⁻¹'),
      'FRESH_INC':('单次采收鲜重','t ha⁻¹'),'FRESH_CUM':('累计采收鲜重','t ha⁻¹'),'TERMINAL_FRESH':('季末鲜果产量','t ha⁻¹')}
    h3=['季节','角色','变量','单位','n','RMSE','nRMSE\n%','Bias','r²','NSE','d']
    r3=[];pages=[]
    for variable_set in [['LAID','LWAD','SWAD'],['FRESH_INC','FRESH_CUM','TERMINAL_FRESH']]:
        page_rows=[]
        for v in variable_set:
            for season in ['25SP','26SP','two_springs']:
                for role in ['calibration','validation','all']:
                    for r in [x for x in tab3 if x['variable']==v and x['season_id']==season and x['dataset_role']==role]:
                        rr=['两春合并' if season=='two_springs' else season,{'calibration':'率定','validation':'留出','all':'全部'}[role],*labels[v],r['n']]
                        rr += [f"{float(r[k]):.2f}" if k=='nrmse_pct' else f"{float(r[k]):.3f}" for k in ['rmse','nrmse_pct','bias','r_squared','nse','d_index']]
                        page_rows.append(rr);r3.append(rr)
        pages.append(page_rows)
    for number,part in enumerate(pages,1):
        d.add_page_break();para(d,'表3 C31两春模拟性能'+(' 续表' if number==2 else ''),size=13,bold=True)
        para(d,'率定与留出处理分别统计；采收按观测当天的归档输出评价。',size=9.5)
        make_table(d,h3,part,[20,18,36,28,12,27,27,27,22,23,23],size=9.2)
        para(d,'注：nRMSE=100×RMSE/评价目标均值；Bias=模拟−评价目标；r²为Pearson相关系数的平方。26SP LAI含12个SLA推算值（率定7、留出5），另提供仅直接测量的指标。留出不等于已证明历史选模独立；重复时点不作为独立田间重复。',size=9)
        if number==2:para(d,'两春合并的季末产量汇总单列，保留NSE等全部指标；留出季末产量NSE约0.006，不能仅凭r²和nRMSE作过强的预测能力表述。',size=9)
    display_csv('Table3_模拟性能_排版版.csv',h3,r3)
    path=TABLES/'C31两春图表阶段2主表.docx';d.save(path)
    # Retain exact, renderer-neutral tables next to their formatted versions.
    for name in ['Table1_trial_design.csv','Table2_key_parameters.csv','Table3_model_performance.csv']:
        (TABLES/name).write_bytes((B/name).read_bytes())
    (TABLES/'table_source_manifest.json').write_text(json.dumps(dict(source_bundle='../paper_data/paper_data_manifest.json',
      font_policy={'latin_digits':'Times New Roman','chinese':'宋体'},row_counts=[23,24,27],data_status='audit_review_unvalidated'),
      ensure_ascii=False,indent=2),encoding='utf-8')
    print(path)

if __name__=='__main__':main()
