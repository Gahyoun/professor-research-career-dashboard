import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const [outputPath, ...files] = process.argv.slice(2);
if (!outputPath || !files.length) {
  throw new Error("usage: extract_openalex_aliases.mjs OUTPUT.json WORKBOOK...");
}

const records = [];
for (const workbookPath of files) {
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));
  for (const sheet of workbook.worksheets.items) {
    const used = sheet.getUsedRange(true);
    const values = used?.values || [];
    if (!values.length) continue;
    const headers = values[0].map((value) => String(value ?? "").trim().toLowerCase());
    const idColumn = headers.findIndex((value) => value === "prof id");
    const nameColumn = headers.findIndex((value) => value === "name");
    for (let index = 1; index < values.length; index++) {
      const row = values[index];
      const ids = [...new Set(row.flatMap((value) => String(value ?? "").match(/A\d{10}/g) || []))];
      if (ids.length < 2) continue;
      records.push({
        workbook: workbookPath,
        sheet: sheet.name,
        row: index + 1,
        source_professor_id: String(row[idColumn] ?? "").trim(),
        name: String(row[nameColumn] ?? "").trim(),
        openalex_ids: ids,
      });
    }
  }
}

await fs.writeFile(outputPath, `${JSON.stringify(records, null, 2)}\n`);
process.stdout.write(`${JSON.stringify({ output: outputPath, records: records.length })}\n`);
