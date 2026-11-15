import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "/home/pth/WORKSHOP/WIDE-FIELD-SOLVER/outputs/knaldgas-focus-20261029";
const sourcePath = "/home/pth/WORKSHOP/WIDE-FIELD-SOLVER/results/knaldgas-focus-20261029/focus_measurements.json";
const rows = JSON.parse(await fs.readFile(sourcePath, "utf8"));

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("Focus results");
sheet.showGridLines = false;
sheet.tabColor = "#1F4E78";

sheet.getRange("A2:J2").merge();
sheet.getRange("A2").values = [["EOS Ra focus sweep, 29 October 2026"]];
sheet.getRange("A2").format.font = { name: "Arial", size: 15, bold: true, color: "#1F1F1F" };
sheet.getRange("A3:J3").format.borders = { bottom: { style: "thin", color: "#7F8C8D" } };

sheet.getRange("A5").values = [["Result"]];
sheet.getRange("B5:J5").merge();
sheet.getRange("B5").values = [["Setting 1 (image 183221) has the smallest fitted FWHM; settings 1 and 2 are both near the sampling limit."]];
sheet.getRange("A6").values = [["Next test"]];
sheet.getRange("B6:J6").merge();
sheet.getRange("B6").values = [["Repeat a finer bracket around settings 1 and 2, including at least one position on the other side of setting 1."]];
sheet.getRange("A7").values = [["Metric"]];
sheet.getRange("B7:J7").merge();
sheet.getRange("B7").values = [["Median minor-axis FWHM from elliptical Gaussian fits to unsaturated stars within 562 px of frame centre."]];
sheet.getRange("A8").values = [["Source"]];
sheet.getRange("B8:J8").merge();
sheet.getRange("B8").values = [["Per Dalgas Jakobsen: https://knaldgas.dk/~pdj/Astro/Fisheye/20261029/"]];
sheet.getRange("A5:A8").format.font = { name: "Arial", size: 10, bold: true, color: "#1F4E78" };
sheet.getRange("B5:J8").format.font = { name: "Arial", size: 10, color: "#1F1F1F" };

const headers = [[
  "Focus setting",
  "Median minor FWHM (px)",
  "Image ID",
  "Ring reading from photo",
  "P25 minor FWHM (px)",
  "P75 minor FWHM (px)",
  "Median minor FWHM on sensor (µm)",
  "Median major FWHM (px)",
  "Accepted / attempted fits",
  "Full-frame detections",
]];
sheet.getRange("A11:J11").values = headers;
sheet.getRange("A11:J11").format.fill = "#1F4E78";
sheet.getRange("A11:J11").format.font = { name: "Arial", size: 10, bold: true, color: "#FFFFFF" };
sheet.getRange("A11:J11").format.horizontalAlignment = "center";
sheet.getRange("A11:J11").format.verticalAlignment = "center";
sheet.getRange("A11:J11").format.wrapText = true;

const values = rows.map((row) => [
  Number(row.focus_ordinal),
  Number(row.minor_fwhm_median_px),
  String(row.image_id),
  String(row.focus_ring_reading),
  Number(row.minor_fwhm_p25_px),
  Number(row.minor_fwhm_p75_px),
  Number(row.minor_fwhm_median_sensor_um),
  Number(row.major_fwhm_median_px),
  `${row.gaussian_fits_accepted} / ${row.gaussian_fits_attempted}`,
  Number(row.all_frame_detections),
]);
sheet.getRange("A12:J18").values = values;
sheet.getRange("A12:J18").format.font = { name: "Arial", size: 10, color: "#1F1F1F" };
sheet.getRange("A12:J18").format.verticalAlignment = "center";
sheet.getRange("A11:J18").format.borders = {
  insideHorizontal: { style: "thin", color: "#D9E2F3" },
  bottom: { style: "thin", color: "#7F8C8D" },
};
sheet.getRange("B12:B18").format.numberFormat = "0.000";
sheet.getRange("E12:H18").format.numberFormat = "0.000";
sheet.getRange("J12:J18").format.numberFormat = "#,##0";
sheet.getRange("A12:A18").format.horizontalAlignment = "center";
sheet.getRange("I12:I18").format.horizontalAlignment = "center";

sheet.getRange("A20:J20").merge();
sheet.getRange("A20").values = [["One analysis pixel is the half-resolution LibRaw sample; 36 mm / 3371 px = 10.68 µm on the sensor. IQR columns describe variation among accepted stars, not uncertainty in the median."]];
sheet.getRange("A20").format.font = { name: "Arial", size: 9, italic: true, color: "#595959" };

sheet.getRange("A1:J20").format.verticalAlignment = "center";
sheet.getRange("A:A").format.columnWidth = 13;
sheet.getRange("B:B").format.columnWidth = 19;
sheet.getRange("C:C").format.columnWidth = 20;
sheet.getRange("D:D").format.columnWidth = 43;
sheet.getRange("E:H").format.columnWidth = 18;
sheet.getRange("I:I").format.columnWidth = 18;
sheet.getRange("J:J").format.columnWidth = 17;
sheet.getRange("2:2").format.rowHeight = 25;
sheet.getRange("11:11").format.rowHeight = 38;
sheet.freezePanes.freezeRows(11);

const chart = sheet.charts.add("line", sheet.getRange("A11:B18"));
chart.title = "Central-star FWHM by focus setting";
chart.hasLegend = false;
chart.xAxis = { axisType: "textAxis", title: "Focus setting", textStyle: { typeface: "Arial" } };
chart.yAxis = { title: "Minor-axis FWHM (half-resolution px)", numberFormatCode: "0.0", numberFormatSourceLinked: false, textStyle: { typeface: "Arial" } };
chart.setPosition("L2", "T18");

workbook.recalculate();
const inspection = await workbook.inspect({
  kind: "table",
  range: "Focus results!A2:J20",
  include: "values,formulas",
  tableMaxRows: 25,
  tableMaxCols: 12,
});
console.log(inspection.ndjson);
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 100 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);

await fs.mkdir(outputDir, { recursive: true });
const preview = await workbook.render({ sheetName: "Focus results", range: "A1:T20", scale: 1, format: "png" });
await fs.writeFile(`${outputDir}/focus-analysis-preview.png`, new Uint8Array(await preview.arrayBuffer()));
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(`${outputDir}/knaldgas-focus-analysis-20261029.xlsx`);
