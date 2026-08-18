import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";
import fs from "node:fs/promises";

const input = process.argv[2];
const outDir = process.argv[3];
await fs.mkdir(outDir, { recursive: true });
const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(input));
const summary = await wb.inspect({kind: "workbook,sheet,region", maxChars: 12000, tableMaxRows: 8, tableMaxCols: 12, tableMaxCellChars: 100});
await fs.writeFile(`${outDir}/inspect.txt`, summary.ndjson ?? String(summary), "utf8");
const sheet = wb.worksheets.getItem("Sheet1");
for (let i = 0; i < 1; i++) {
  const used = sheet.getUsedRange();
  const values = used ? used.values : [];
  await fs.writeFile(`${outDir}/sheet_${i}.json`, JSON.stringify({name: sheet.name, values}, null, 2), "utf8");
  const preview = await wb.render({sheetName: sheet.name, autoCrop: "all", scale: 1, format: "png"});
  await fs.writeFile(`${outDir}/sheet_${i}.png`, new Uint8Array(await preview.arrayBuffer()));
}
