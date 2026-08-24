import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const files = process.argv.slice(2);
for (const path of files) {
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(path));
  const report = await workbook.inspect({
    kind: "match",
    searchTerm: "A\\d{10}.*A\\d{10}",
    options: { useRegex: true, maxResults: 100 },
    maxChars: 12000,
    summary: "cells containing two or more OpenAlex author IDs",
  });
  process.stdout.write(`${JSON.stringify({ path })}\n${report.ndjson}\n`);
}
