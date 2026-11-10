import fs from 'node:fs/promises';
import path from 'node:path';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const dir=path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/,'$1'));
const actualDir=decodeURIComponent(dir);
const data=JSON.parse(await fs.readFile(path.join(actualDir,'reviewed_results.json'),'utf8'));
const wb=Workbook.create();
const source='当前：D:\\三季节数据汇总；参照：D:\\Tomato_Cal\\data\\user\\ref\\DSSAT文件。2026-10-03只读检查，原始文件未修改。';
const specs=[
 {name:'人工处理清单',headers:['编号','优先级','类型','问题','位置','证据','处理建议','置信度','状态','处理决定','依据'],rows:data.issues,widths:[8,8,16,38,40,65,65,10,12,30,30]},
 {name:'疑点明细',headers:['问题编号','文件','工作表','单元格或范围','当前值','疑点依据','处理建议','状态','处理说明'],rows:data.details,widths:[10,42,14,24,16,72,55,12,30]},
 {name:'统计筛查',headers:['文件','工作表','单元格','指标','日期','器官','土层','当前值','筛查方法','下界','上界','建议','小区号','重复','水处理','氮处理'],rows:data.candidates,widths:[44,14,12,25,14,10,12,15,24,15,15,48,12,10,10,10]},
 {name:'数据覆盖',headers:['文件','主数据页','记录行数','候选键数','重复键组数','日期','小区编号','重复或行号'],rows:data.coverage,widths:[50,18,14,14,14,90,50,20]},
 {name:'分期字段概况',headers:['文件','工作表','日期','器官','土层','字段','记录数','数值数','缺失数','缺失率','最小值','中位数','最大值'],rows:data.profiles,widths:[44,16,14,10,12,30,12,12,12,12,16,16,16]},
 {name:'同步值差异',headers:['文件','工作表','当前单元格','当前字段','当前值','参照单元格','参照字段','参照值','差异类型','处理状态','处理说明'],rows:data.semantic,widths:[44,18,15,23,22,15,23,22,22,16,36]}
];
for(let ix=0;ix<specs.length;ix++){
 const p=specs[ix];const sh=wb.worksheets.add(p.name);sh.showGridLines=false;
 sh.getRange('A2').values=[[p.name+'（2026-10-03）']];sh.getRange('A2').format.font={name:'Arial',size:14,bold:true};
 sh.getRange('A3').values=[[source]];sh.getRange('A3').format.font={name:'Arial',size:10,color:'#596579'};
 const matrix=[p.headers,...p.rows.map(row=>row.map(v=>typeof v==='string'&&v.startsWith('=')?"'"+v:v??null))];
 const rng=sh.getRangeByIndexes(4,0,matrix.length,p.headers.length);rng.values=matrix;
 rng.format.font={name:'Arial',size:10,color:'#192536'};rng.format.verticalAlignment='center';rng.format.rowHeight=30;
 sh.getRangeByIndexes(4,0,1,p.headers.length).format={fill:'#203A5A',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},rowHeight:32,horizontalAlignment:'center',verticalAlignment:'center'};
 for(let c=0;c<p.headers.length;c++)sh.getRangeByIndexes(4,c,matrix.length,1).format.columnWidth=p.widths[c];
 if(p.rows.length)sh.getRangeByIndexes(5,0,p.rows.length,p.headers.length).format.wrapText=true;
 sh.tables.add(sh.getRangeByIndexes(4,0,matrix.length,p.headers.length).address,true,'AuditTable'+ix);
 sh.freezePanes.freezeRows(5);
 if(ix===0){
   sh.tabColor='#203A5A';
   sh.getRangeByIndexes(5,3,p.rows.length,5).format.rowHeight=72;
   sh.getRangeByIndexes(5,8,p.rows.length,3).format.fill='#FFF3D0';
   sh.getRangeByIndexes(5,8,p.rows.length,1).dataValidation={rule:{type:'list',values:['待核实','已修正','保留原值','确认缺测','排除分析','需补资料']}};
   sh.getRangeByIndexes(5,1,p.rows.length,1).conditionalFormats.add('containsText',{text:'P1',format:{font:{bold:true,color:'#A61C2B'},fill:'#FCE7E9'}});
 }
 if(ix===1)sh.getRangeByIndexes(5,5,p.rows.length,2).format.rowHeight=50;
 if(ix===2)sh.getRangeByIndexes(5,7,p.rows.length,1).setNumberFormat('0.000000');
 if(ix===4){sh.getRangeByIndexes(5,9,p.rows.length,1).setNumberFormat('0.0%');sh.getRangeByIndexes(5,10,p.rows.length,3).setNumberFormat('0.000000');}
 if(ix===5)sh.getRangeByIndexes(5,10,p.rows.length,1).format.fill='#FFF3D0';
}
wb.recalculate();
console.log((await wb.inspect({kind:'table',range:'人工处理清单!A5:F9',include:'values',tableMaxRows:5,tableMaxCols:6,maxChars:2200})).ndjson);
for(const sh of specs){const b=await wb.render({sheetName:sh.name,range:sh.name==='人工处理清单'?'A2:G10':'A2:H9',scale:1,format:'png'});await fs.writeFile(path.join(actualDir,'preview_'+sh.name+'.png'),new Uint8Array(await b.arrayBuffer()));}
await(await SpreadsheetFile.exportXlsx(wb)).save(path.join(actualDir,'数据清洗人工核对清单.xlsx'));
console.log('Exported audit workbook; sheets='+specs.length);
