import fs from 'node:fs/promises';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';

const root = 'E:/development/AI-Project/outputs/cinema-rag-values-2026-09-24';
const source = 'E:/development/AI-Project/deliverables/影院购退票与营业服务_RAG问答知识库.xlsx';
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(source));
const overview = await workbook.inspect({
  kind: 'workbook,sheet,table',
  maxChars: 3000,
  tableMaxRows: 4,
  tableMaxCols: 6,
  tableMaxCellChars: 100,
});
console.log(overview.ndjson ?? JSON.stringify(overview));
const sheets = await workbook.inspect({ kind: 'sheet', include: 'id,name' });
console.log('\nSHEETS\n' + (sheets.ndjson ?? JSON.stringify(sheets)));
const sheet = workbook.worksheets.getItem('RAG问答库');
const values = sheet.getRange('A1:F57').values;
console.log('\nFAQ IDS, STATUS, QUESTIONS\n' + JSON.stringify(values.slice(1).map(r => [r[0], r[4], String(r[2]).split('\n')[0]]), null, 2));
const preview = await workbook.render({ sheetName: 'RAG问答库', autoCrop: 'all', scale: 0.6, format: 'png' });
await fs.writeFile(`${root}/before_RAG问答库.png`, new Uint8Array(await preview.arrayBuffer()));
console.log('\nPREVIEW ' + `${root}/before_RAG问答库.png`);
