import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const workbook = Workbook.create();
const theme = {
  white: "#FFFFFF",
  navy: "#323366",
  purple: "#544F7D",
  cyan: "#60C4E4",
  soft: "#EEF9FD",
};
const NOT_OBSERVED = "لم يتم الرصد";
const NOT_APPLICABLE = "غير منطبق";

function columnName(index) {
  let name = "";
  let n = index + 1;
  while (n > 0) {
    const rem = (n - 1) % 26;
    name = String.fromCharCode(65 + rem) + name;
    n = Math.floor((n - 1) / 26);
  }
  return name;
}

function addSheet(name, headers, rows, tableName, options = {}) {
  const sheet = workbook.worksheets.add(name);
  sheet.showGridLines = false;
  sheet.getRangeByIndexes(0, 0, rows.length + 1, headers.length).values = [headers, ...rows];
  const range = `A1:${columnName(headers.length - 1)}${rows.length + 1}`;
  const header = sheet.getRange(`A1:${columnName(headers.length - 1)}1`);
  header.format = {
    fill: theme.navy,
    font: { bold: true, color: theme.white },
    wrapText: true,
  };
  sheet.getRange(range).format.borders = { preset: "all", style: "thin", color: "#DDE6F2" };
  sheet.getRange(`A2:${columnName(headers.length - 1)}${rows.length + 1}`).format = {
    fill: theme.white,
    wrapText: true,
  };
  sheet.freezePanes.freezeRows(1);
  const table = sheet.tables.add(range, true, tableName);
  table.showFilterButton = true;
  table.showBandedColumns = false;
  try {
    table.style = "TableStyleMedium2";
  } catch {}
  sheet.getRange(range).format.autofitColumns();
  sheet.getRange(range).format.autofitRows();
  if (options.required?.length) {
    options.required.forEach((headerName) => {
      const idx = headers.indexOf(headerName);
      if (idx >= 0) {
        const col = columnName(idx);
        sheet.getRange(`${col}1:${col}${rows.length + 1}`).format = {
          fill: idx === 0 ? theme.navy : "#EEF9FD",
          font: idx === 0 ? { bold: true, color: theme.white } : undefined,
        };
      }
    });
  }
  return sheet;
}

function addListValidation(sheet, colIndex, values, maxRows = 200) {
  const col = columnName(colIndex);
  sheet.dataValidations.add({
    range: `${col}2:${col}${maxRows}`,
    rule: { type: "list", values },
  });
}

function addNumberValidation(sheet, headers, names, maxRows = 200) {
  names.forEach((name) => {
    const idx = headers.indexOf(name);
    if (idx >= 0) {
      const col = columnName(idx);
      sheet.dataValidations.add({
        range: `${col}2:${col}${maxRows}`,
        rule: { type: "decimal", operator: "greaterThanOrEqual", formula1: 0 },
      });
    }
  });
}

const instructions = workbook.worksheets.add("التعليمات");
instructions.showGridLines = false;
instructions.getRange("A1:H1").merge();
instructions.getRange("A1").values = [["قالب إنتاجية التعليم الإلكتروني الأسبوعية"]];
instructions.getRange("A1").format = {
  fill: theme.navy,
  font: { bold: true, color: theme.white, size: 16 },
};
instructions.getRange("A3:H12").values = [
  ["طريقة الاستخدام", "", "", "", "", "", "", ""],
  ["1", "انسخ هذا الملف لكل أسبوع جديد.", "", "", "", "", "", ""],
  ["2", "عبئ البيانات العامة أولًا ثم الحلق والبرامج والصور والشواهد.", "", "", "", "", "", ""],
  ["3", "استخدم 0 فقط عندما يكون الصفر قيمة حقيقية.", "", "", "", "", "", ""],
  ["4", "استخدم عبارة لم يتم الرصد عندما لم تصل البيانات.", "", "", "", "", "", ""],
  ["5", "استخدم غير منطبق للحقل الذي لا ينطبق على النشاط.", "", "", "", "", "", ""],
  ["6", "ارفع الصور على Google Drive، واجعل الصلاحية: أي شخص لديه الرابط يمكنه العرض.", "", "", "", "", "", ""],
  ["7", "شغل: python tools/import_excel.py productivity-data-template.xlsx --validate-only", "", "", "", "", "", ""],
  ["8", "ثم شغل: python tools/import_excel.py productivity-data-template.xlsx --publish", "", "", "", "", "", ""],
  ["تنبيه", "ضع رابط مشاركة Google Drive للصورة فقط. لا تستخدم رابط مجلد أو مستند، ولا روابط javascript: أو data:.", "", "", "", "", "", ""],
];
instructions.getRange("A3:H12").format = { wrapText: true };
instructions.getRange("A3:H3").format = { fill: theme.cyan, font: { bold: true, color: theme.navy } };
instructions.getRange("A1:H12").format.autofitColumns();

addSheet(
  "البيانات العامة",
  ["السنة", "الشهر", "الأسبوع", "عنوان الإنتاجية", "وصف مختصر", "تاريخ البداية", "تاريخ النهاية", "تاريخ التحديث", "حالة الإنتاجية", "ملاحظات"],
  [[2026, 5, 5, "إنتاجية شهر 5 - الأسبوع الخامس", "مثال إنتاجية أسبوعية مولدة من Excel", new Date("2026-05-24"), new Date("2026-05-30"), new Date("2026-05-30"), "منشور", "يمكن حذف هذا المثال"]],
  "GeneralData",
  { required: ["السنة", "الشهر", "الأسبوع", "عنوان الإنتاجية", "حالة الإنتاجية"] }
);

const halaqatHeaders = ["معرف الحلقة", "اسم الحلقة أو نوعها", "عدد الحلق", "عدد المعلمين", "عدد المشرفين", "عدد الطلاب", "الأوجه المحفوظة", "الأجزاء المحفوظة", "الأوجه المراجعة", "الأجزاء المراجعة", "ساعات البث", "أصغر طالب", "أكبر طالب", "المختبرون", "المجتازون", "كاملو القرآن", "رابط الشاهد", "ملاحظات"];
const halaqatSheet = addSheet(
  "الحلق",
  halaqatHeaders,
  [["h-001", "حلقة نموذجية تجريبية", 3, 3, 1, 42, 360, 18, 520, 26, 12, 8, 18, 4, 3, 0, "https://example.com/evidence/h-001", "مثال يمكن حذفه"]],
  "HalaqatTable",
  { required: ["معرف الحلقة", "اسم الحلقة أو نوعها"] }
);

const programHeaders = ["معرف البرنامج", "اسم البرنامج", "نوع البرنامج", "تاريخ البرنامج", "المستفيدون", "الدارسون", "المعلمون", "المشرفون", "المتطوعون", "ساعات التطوع", "ساعات البث", "رابط الشاهد", "وصف مختصر", "ملاحظات"];
const programsSheet = addSheet(
  "البرامج النوعية",
  programHeaders,
  [
    ["p-001", "برنامج مهاري للقرآن", "برنامج نوعي", new Date("2026-05-26"), 120, 80, 4, 1, 8, 24, 6, "https://example.com/evidence/p-001", "برنامج تجريبي يحتوي عدة صور", "مثال يمكن حذفه"],
    ["p-002", "برنامج بلا صور", "مبادرة", new Date("2026-05-28"), 0, 0, NOT_OBSERVED, NOT_APPLICABLE, 0, 0, 0, "https://example.com/evidence/p-002", "مثال لاختبار الصفر وعدم الرصد وغير منطبق", ""],
  ],
  "ProgramsTable",
  { required: ["معرف البرنامج", "اسم البرنامج"] }
);

const testsSheet = addSheet("الاختبارات", ["المختبرون", "المجتازون", "كاملو القرآن", "ملاحظات"], [[4, 3, 0, "مثال"]], "TestsTable");
const extraSheet = addSheet("المؤشرات الإضافية", ["القسم", "اسم المؤشر", "القيمة", "الوحدة", "قاعدة التجميع", "الترتيب", "ملاحظات"], [["عام", "عدد المشاركات", 120, "مشاركة", "sum", 1, "مثال"]], "ExtraMetricsTable");
const imagesSheet = addSheet(
  "الصور",
  ["image_id", "related_type", "related_id", "drive_url", "alt_text", "caption", "sort_order", "is_primary", "display_status"],
  [
    ["img-001", "برنامج", "p-001", "https://drive.google.com/file/d/1SDbKsxMh7KNYpbWsSZrrZHt1nMJE-03t/view?usp=drive_link", "صورة رئيسية لبرنامج مهاري", "الصورة الرئيسية من Google Drive", 1, "نعم", "ظاهر"],
    ["img-002", "برنامج", "p-001", "https://drive.google.com/open?id=1SDbKsxMh7KNYpbWsSZrrZHt1nMJE-03t", "صورة إضافية لفعالية تعليمية", "صورة من المعرض من Google Drive", 2, "لا", "ظاهر"],
  ],
  "ImagesTable",
  { required: ["image_id", "related_id", "drive_url", "alt_text"] }
);
const linksSheet = addSheet(
  "الشواهد والروابط",
  ["معرف العنصر", "نوع العنصر", "الرابط", "وصف الرابط", "حالة العرض"],
  [["p-001", "برنامج", "https://example.com/evidence/p-001", "شاهد البرنامج", "ظاهر"]],
  "EvidenceTable"
);
const listsSheet = addSheet(
  "القوائم المرجعية",
  ["حالات الإنتاجية", "حالات العرض", "نعم/لا", "نوع العنصر", "قواعد التجميع", "قيم خاصة"],
  [
    ["منشور", "ظاهر", "نعم", "برنامج", "sum", NOT_OBSERVED],
    ["مسودة", "مخفي", "لا", "حلقة", "average", NOT_APPLICABLE],
    ["مؤرشف", "", "", "فعالية", "latest", ""],
    ["", "", "", "", "min", ""],
    ["", "", "", "", "max", ""],
    ["", "", "", "", "unique", ""],
    ["", "", "", "", "noAggregation", ""],
  ],
  "ReferenceLists"
);

addListValidation(workbook.worksheets.getItem("البيانات العامة"), 8, ["منشور", "مسودة", "مؤرشف"], 50);
addListValidation(imagesSheet, 1, ["برنامج", "حلقة", "فعالية"], 200);
addListValidation(imagesSheet, 7, ["نعم", "لا"], 200);
addListValidation(imagesSheet, 8, ["ظاهر", "مخفي"], 200);
addListValidation(linksSheet, 1, ["برنامج", "حلقة", "فعالية"], 200);
addListValidation(linksSheet, 4, ["ظاهر", "مخفي"], 200);
addListValidation(extraSheet, 4, ["sum", "average", "latest", "min", "max", "unique", "noAggregation"], 200);
addNumberValidation(halaqatSheet, halaqatHeaders, halaqatHeaders.filter((h) => !["معرف الحلقة", "اسم الحلقة أو نوعها", "رابط الشاهد", "ملاحظات"].includes(h)));
addNumberValidation(programsSheet, programHeaders, ["المستفيدون", "الدارسون", "المعلمون", "المشرفون", "المتطوعون", "ساعات التطوع", "ساعات البث"]);
addNumberValidation(testsSheet, ["المختبرون", "المجتازون", "كاملو القرآن", "ملاحظات"], ["المختبرون", "المجتازون", "كاملو القرآن"]);
addNumberValidation(imagesSheet, ["image_id", "related_type", "related_id", "drive_url", "alt_text", "caption", "sort_order", "is_primary", "display_status"], ["sort_order"]);

for (const sheet of workbook.worksheets.items) {
  const used = sheet.getUsedRange(true);
  if (used) {
    used.format.font = { name: "Arial", size: 11, color: theme.navy };
    used.format.wrapText = true;
    used.format.autofitColumns();
  }
}

await fs.mkdir("outputs", { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save("productivity-data-template.xlsx");
await output.save("outputs/productivity-data-template.xlsx");
console.log("productivity-data-template.xlsx");
