import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";
import fs from "node:fs/promises";

const input = process.argv[2];
const output = process.argv[3];
const auditPath = process.argv[4];
const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(input));
const sheet = wb.worksheets.getItem("Sheet1");
const used = sheet.getUsedRange();
const values = used.values;
const corrections = [
  { dateSerial: 45799, trno: 5, rep: 2, old: 0.893580406256722, value: 0.9580 },
  { dateSerial: 45827, trno: 5, rep: 2, old: 0.893580406256722, value: 0.9580 },
  { dateSerial: 45799, trno: 13, rep: 3, old: 0.784845063354661, value: 0.9680 },
  { dateSerial: 45827, trno: 13, rep: 3, old: 0.784845063354661, value: 0.9680 },
];
const applied = [];
for (let i = 1; i < values.length; i++) {
  const row = values[i];
  const hit = corrections.find(c => row[0] === c.dateSerial && row[1] === c.trno && row[4] === c.rep && Math.abs(Number(row[9]) - c.old) < 1e-8);
  if (hit) {
    const excelRow = i + 1;
    sheet.getRange(`J${excelRow}`).values = [[hit.value]];
    applied.push({ ...hit, excel_row: excelRow, column: "J", actual_old: row[9] });
  }
}
if (applied.length !== corrections.length) throw new Error(`Expected ${corrections.length} corrections, applied ${applied.length}`);
const out = await SpreadsheetFile.exportXlsx(wb);
await out.save(output);
await fs.writeFile(auditPath, JSON.stringify({input, output, sheet: "Sheet1", corrections: applied}, null, 2), "utf8");
console.log(JSON.stringify({output, applied}, null, 2));
