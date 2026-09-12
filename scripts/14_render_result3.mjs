import fs from 'node:fs/promises';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';
const root='C:/Users/dell/Desktop/C题02/cumcm2026_c_microgrid';
const input=await FileBlob.load(`${root}/outputs/q3/result3.xlsx`);
const workbook=await SpreadsheetFile.importXlsx(input);
const summary=await workbook.inspect({kind:'sheet',include:'id,name',maxChars:4000});
console.log(summary.ndjson);
await fs.mkdir(`${root}/reports/figures/q3/workbook_preview`,{recursive:true});
for (const [sheetName,range] of [['计划购电量','A1:H8'],['调整购电量','A1:H8'],['充放电量','A1:F14'],['紧急购电量','A1:C16']]) {
  const check=await workbook.inspect({kind:'table',range:`${sheetName}!${range}`,include:'values,formulas',tableMaxRows:16,tableMaxCols:8,maxChars:5000});
  console.log(check.ndjson);
  const image=await workbook.render({sheetName,range,scale:1.5,format:'png'});
  await fs.writeFile(`${root}/reports/figures/q3/workbook_preview/${sheetName}.png`,new Uint8Array(await image.arrayBuffer()));
}
