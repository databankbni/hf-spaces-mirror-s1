/** CSV/TXT parser for participantEmail + modelName batch score uploads. */
export interface ParsedCsvRow {
  participantEmail: string;
  modelName: string;
  scores: Record<string, number>;
}

export interface CsvParseResult {
  rows: ParsedCsvRow[];
  errors: string[];
  metricCodes: string[];
}

export function parseCsv(text: string, validMetricCodes: string[]): CsvParseResult {
  const errors: string[] = [];
  const rows: ParsedCsvRow[] = [];
  const lines = text.replace(/^\uFEFF/, "").replace(/\r\n/g, "\n").replace(/\r/g, "\n")
    .split("\n").filter((line) => line.trim());
  if (lines.length < 2) {
    return { rows, errors: ["The file must include a header row and at least one data row"], metricCodes: [] };
  }

  const delimiter = lines[0].includes("\t") ? "\t" : ",";
  const headers = lines[0].split(delimiter).map((header) => header.trim());
  const emailIndex = headers.findIndex((header) => header.toLowerCase() === "participantemail");
  const modelNameIndex = headers.findIndex((header) => header.toLowerCase() === "modelname");
  if (emailIndex < 0 || modelNameIndex < 0) {
    return { rows, errors: ["The header must include participantEmail and modelName"], metricCodes: [] };
  }

  const columns = new Map<number, string>();
  headers.forEach((header, index) => {
    if (index === emailIndex || index === modelNameIndex) return;
    const metric = validMetricCodes.find((code) => code.toLowerCase() === header.toLowerCase());
    if (metric) columns.set(index, metric);
    else errors.push(`Column ${index + 1} "${header}" is not a valid metric code and was skipped`);
  });
  if (!columns.size) {
    return { rows, errors: [...errors, "No valid metric code columns were found"], metricCodes: [] };
  }

  lines.slice(1).forEach((line, rowIndex) => {
    const cells = line.split(delimiter).map((cell) => cell.trim());
    const participantEmail = cells[emailIndex] || "";
    const modelName = cells[modelNameIndex] || "";
    if (!participantEmail || !modelName) {
      errors.push(`Row ${rowIndex + 2}: participantEmail and modelName are required`);
      return;
    }
    const scores: Record<string, number> = {};
    columns.forEach((metricCode, columnIndex) => {
      const raw = cells[columnIndex];
      if (!raw) return;
      const value = Number(raw);
      if (Number.isNaN(value)) errors.push(`Row ${rowIndex + 2}: ${metricCode} value "${raw}" is not numeric`);
      else scores[metricCode] = value;
    });
    if (Object.keys(scores).length) rows.push({ participantEmail, modelName, scores });
    else errors.push(`Row ${rowIndex + 2}: no valid scores were found`);
  });

  return { rows, errors, metricCodes: [...new Set(columns.values())] };
}
