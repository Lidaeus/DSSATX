import fs from 'node:fs/promises';
import {Workbook,SpreadsheetFile,FileBlob} from '@oai/artifact-tool';
const dir='D:/三季节数据汇总/数据质控_20261007/预审_20261007';
const target='D:/三季节数据汇总/数据质控_20261007/更新数据核对与统计筛查.xlsx';
if(process.argv[2]==='verify-target'){
 const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(target));
 console.log((await wb.inspect({kind:'table',range:'更新统计筛查!S96:AB100',include:'values',tableMaxRows:5,tableMaxCols:10,maxChars:2000})).ndjson);
 for(const [name,range] of [['品质建议','S96:X100'],['养分建议','S190:X194'],['处理响应','Y96:AB100'],['新增表头','S5:AB5']]){
  const img=await wb.render({sheetName:'更新统计筛查',range,scale:1,format:'png'});
  await fs.writeFile(dir+'/保存后_'+name+'.png',new Uint8Array(await img.arrayBuffer()));
 }
}else if(process.argv[2]==='preview'){
 const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(target));
 console.log((await wb.inspect({kind:'table',range:'更新统计筛查!L94:R101',include:'values',tableMaxRows:8,tableMaxCols:7,maxChars:2000})).ndjson);
 const img=await wb.render({sheetName:'更新统计筛查',range:'L94:R101',scale:1.3,format:'png'});
 await fs.writeFile(dir+'/原审核区域.png',new Uint8Array(await img.arrayBuffer()));
}else{
 const d=JSON.parse(await fs.readFile(dir+'/逐项预审建议.json','utf8'));
 const wb=Workbook.create(); const sh=wb.worksheets.add('更新统计筛查');
 sh.getRange('S3').values=[[d.subtitle]];
 sh.getRange('S3').format.font={name:'Arial',size:10,color:'#526075'};
 sh.getRange('S5:AB5').values=[d.headers];
 sh.getRange('S5:AB5').format={fill:'#203A5A',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},horizontalAlignment:'center',verticalAlignment:'center',wrapText:true,rowHeight:34};
 const widths=[30,72,22,16,52,22,80,65,26,16];
 for(let c=0;c<10;c++)sh.getRangeByIndexes(4,18+c,218,1).format.columnWidth=widths[c];
 for(const item of d.cases){
   for(const r of item.audit_rows){
     const range=sh.getRange(`S${r}:AB${r}`);range.values=[item.output];
     range.format={font:{name:'Arial',size:10,color:'#192536'},verticalAlignment:'center',wrapText:true,rowHeight:94};
     sh.getRange(`S${r}`).format.fill=item.decision==='倾向保留原值'?'#E9F2EB':item.decision==='核验后倾向均值替代'?'#FFF0D5':'#EEF0F4';
     sh.getRange(`U${r}`).setNumberFormat('0.000000');
     sh.getRange(`X${r}`).setNumberFormat('0.00%');
   }
 }
 sh.getRange('S225').values=[['预审依据与适用范围（原始仪器、取样或称重记录仍须另核）']];
 sh.getRange('S225').format.font={name:'Arial',size:11,bold:true,color:'#203A5A'};
 for(let i=0;i<d.sources.length;i++){
   const r=227+i; const src=d.sources[i];
   sh.getRange(`S${r}`).values=[[src.id]];
   sh.getRange(`T${r}`).values=[[src.title+'。'+src.use]];
   sh.getRange(`W${r}`).values=[[src.url]];
   sh.getRange(`S${r}:AB${r}`).format={font:{name:'Arial',size:10,color:'#192536'},verticalAlignment:'center',wrapText:true,rowHeight:90};
 }
 wb.recalculate();
 console.log((await wb.inspect({kind:'table',range:'S96:X100',sheetId:'更新统计筛查',include:'values',tableMaxRows:5,tableMaxCols:6,maxChars:2200})).ndjson);
 for(const [name,range] of [['品质建议','S96:X100'],['氮磷钾建议','S198:X203'],['处理响应比较','Y96:AB100'],['文献依据','S225:W233']]){
   const img=await wb.render({sheetName:'更新统计筛查',range,scale:1,format:'png'});
   await fs.writeFile(dir+'/预审_'+name+'.png',new Uint8Array(await img.arrayBuffer()));
 }
 await(await SpreadsheetFile.exportXlsx(wb)).save(dir+'/_新增预审列.xlsx');
}
