import fs from 'node:fs/promises';
import path from 'node:path';
import {Workbook,SpreadsheetFile,FileBlob} from '@oai/artifact-tool';
const dir='D:/三季节数据汇总/数据质控_20261007';
const source='D:/三季节数据汇总/2025春/2025春土壤含水量数据集.xlsx';
if(process.argv[2]==='preview-source'||process.argv[2]==='preview-soil'){
 const soil=process.argv[2]==='preview-soil';const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(soil?'D:/三季节数据汇总/2025秋/20260106_2号棚取土.xlsx':source));
 console.log((await wb.inspect({kind:'table',range:'Sheet1!B255:G258',include:'values,formulas',tableMaxRows:4,tableMaxCols:6,maxChars:1800})).ndjson);
 const im=await wb.render({sheetName:'Sheet1',range:soil?'A1:J8':'A253:G260',scale:1.5,format:'png'});await fs.writeFile(path.join(dir,soil?'原秋季取土区域.png':'原水分表待改区域.png'),new Uint8Array(await im.arrayBuffer()));
}else if(process.argv[2]==='cell-patch'){
 const wb=Workbook.create();const sh=wb.worksheets.add('Sheet1');sh.getRange('C257').values=[[6702]];wb.recalculate();
 await(await SpreadsheetFile.exportXlsx(wb)).save(path.join(dir,'_C257值片段.xlsx'));
 console.log('Authored numeric replacement 6702 with Artifact Tool');
}else if(process.argv[2]==='soil-patch'){
 const d=JSON.parse(await fs.readFile(path.join(dir,'snapshot.json'),'utf8'));const s=d.current['2025秋\\20260106_2号棚取土.xlsx'].sheets.Sheet1;
 const v=a=>s.formulas[a]?.cached??s.cells[a];const wb=Workbook.create();const sh=wb.worksheets.add('Sheet1');
 sh.getRange('B2:D241').values=Array.from({length:240},(_,i)=>['B','C','D'].map(c=>v(c+(i+2))));
 sh.getRange('H2:H241').formulas=Array.from({length:240},(_,i)=>{const r=i+2;return [`=(C${r}-D${r})/(D${r}-B${r}*100)`]});
 wb.recalculate();await(await SpreadsheetFile.exportXlsx(wb)).save(path.join(dir,'_秋季水分公式片段.xlsx'));
 console.log((await wb.inspect({kind:'table',range:'Sheet1!B2:H4',include:'values,formulas',tableMaxRows:3,tableMaxCols:7,maxChars:1200})).ndjson);
}else{
 const d=JSON.parse(await fs.readFile(path.join(dir,'reviewed_results.json'),'utf8'));
 const wb=Workbook.create();
 const specs=[
 {name:'事项处理状态',head:['编号','本次状态','事项','处理或依据','后续行动'],rows:d.issue_status,widths:[10,22,42,86,64]},
 {name:'更新统计筛查',head:['文件','工作表或视图','位置','指标','日期','器官','土层','值','方法','下界','上界','小区或样本号','重复','水处理','氮处理','解释','处理状态','处理决定'],rows:d.screens,widths:[46,30,25,28,14,10,14,15,28,15,15,15,10,12,12,58,18,36]},
 {name:'SPAD建议排除',head:['文件','工作表','单元格','日期','小区','水处理','氮处理','生物学重复','建议排除值','保留第1次','保留第2次','保留第3次','四次均值','三次均值','均值变化','相对变化','依据','处理状态'],rows:d.spad,widths:[48,14,14,16,10,12,12,16,16,16,16,16,16,16,16,16,52,18]},
 {name:'SPAD重复均值',head:['日期','小区','水处理','氮处理','生物学重复','原读数数','原均值','前三次均值','前三次SD','保留读数数','均值变化'],rows:d.spad_means,widths:[16,12,12,12,18,16,16,18,18,18,18]},
 {name:'分析范围',head:['文件','工作表或视图','原记录数','纳入范围数','指定排除数','整枝空行排除数','保留日期','保留小区或样本号'],rows:d.coverage,widths:[52,32,16,18,18,22,75,50]},
 {name:'已确认替代值',head:['文件','工作表','位置','当前值','来源说明','分析口径'],rows:d.confirmed_fill,widths:[52,22,14,22,55,65]}
 ];
 for(let i=0;i<specs.length;i++){
  const p=specs[i];const sh=wb.worksheets.add(p.name);sh.showGridLines=false;
  sh.getRange('A2').values=[[p.name+'（2026-10-07）']];sh.getRange('A2').format.font={name:'Arial',size:14,bold:true};
  sh.getRange('A3').values=[['当前Excel与用户确认口径。统计表已按建议保留前三次SPAD测定计算；原SPAD未删除。']];sh.getRange('A3').format.font={name:'Arial',size:10,color:'#526075'};
  const vals=[p.head,...p.rows.map(r=>r.map(v=>v??null))];const rng=sh.getRangeByIndexes(4,0,vals.length,p.head.length);rng.values=vals;
  rng.format.font={name:'Arial',size:10,color:'#192536'};rng.format.verticalAlignment='center';rng.format.rowHeight=i===0?72:34;
  sh.getRangeByIndexes(4,0,1,p.head.length).format={fill:'#203A5A',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},horizontalAlignment:'center',verticalAlignment:'center',rowHeight:34};
  for(let c=0;c<p.head.length;c++)sh.getRangeByIndexes(4,c,vals.length,1).format.columnWidth=p.widths[c];
  if(p.rows.length)sh.getRangeByIndexes(5,0,p.rows.length,p.head.length).format.wrapText=true;
  sh.tables.add(sh.getRangeByIndexes(4,0,vals.length,p.head.length).address,true,'ReviewTable'+i);sh.freezePanes.freezeRows(5);
  if(i===0)sh.tabColor='#203A5A';
  if(i===1){sh.getRangeByIndexes(5,7,p.rows.length,1).setNumberFormat('0.000000');sh.getRangeByIndexes(5,16,p.rows.length,2).format.fill='#FFF3D0';sh.getRangeByIndexes(5,16,p.rows.length,1).dataValidation={rule:{type:'list',values:['待人工核查','保留原值','已修正','排除分析','确认缺测']}};}
  if(i===2){sh.getRangeByIndexes(5,12,p.rows.length,3).setNumberFormat('0.0000');sh.getRangeByIndexes(5,15,p.rows.length,1).setNumberFormat('0.00%');}
  if(i===3)sh.getRangeByIndexes(5,6,p.rows.length,3).setNumberFormat('0.0000');
  if(i===4)sh.getRangeByIndexes(5,6,p.rows.length,1).format.rowHeight=60;
 }
 wb.recalculate();
 console.log((await wb.inspect({kind:'table',range:'SPAD建议排除!C5:I11',include:'values',tableMaxRows:7,tableMaxCols:7,maxChars:1800})).ndjson);
 for(const p of specs){const im=await wb.render({sheetName:p.name,range:p.name==='事项处理状态'?'A2:E10':p.name==='SPAD建议排除'?'C2:O11':'A2:H10',scale:1,format:'png'});await fs.writeFile(path.join(dir,'preview_'+p.name+'.png'),new Uint8Array(await im.arrayBuffer()));}
 await(await SpreadsheetFile.exportXlsx(wb)).save(path.join(dir,'更新数据核对与统计筛查.xlsx'));
 console.log('Saved updated workbook');
}
