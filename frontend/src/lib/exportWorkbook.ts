/** Zengin CSV / Excel dışa aktarma — özet + sıralama + uyarı sayfaları. */

import * as XLSX from "xlsx";

export type ExportMeta = Record<string, string | number | boolean | null | undefined>;

export interface SheetTable {
  name: string;
  headers: string[];
  rows: unknown[][];
}

function escapeCsvCell(value: unknown): string {
  const s = value === null || value === undefined ? "" : String(value);
  if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function metaRows(meta: ExportMeta): string[][] {
  const now = new Date().toLocaleString("tr-TR");
  const rows: string[][] = [
    ["Alan", "Değer"],
    ["Dışa aktarma zamanı", now],
  ];
  for (const [k, v] of Object.entries(meta)) {
    if (v === undefined || v === null || v === "") continue;
    rows.push([k, String(v)]);
  }
  return rows;
}

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

/** Türkçe başlıklı CSV: üstte meta bloğu, sonra boş satır, sonra tablo. */
export function downloadRichCsv(opts: {
  filename: string;
  meta: ExportMeta;
  headers: string[];
  rows: unknown[][];
  extraSections?: { title: string; headers: string[]; rows: unknown[][] }[];
}): void {
  const lines: string[] = [];
  for (const row of metaRows(opts.meta)) {
    lines.push(row.map(escapeCsvCell).join(","));
  }
  lines.push("");
  lines.push(opts.headers.map(escapeCsvCell).join(","));
  for (const row of opts.rows) {
    lines.push(row.map(escapeCsvCell).join(","));
  }
  for (const section of opts.extraSections ?? []) {
    lines.push("");
    lines.push(escapeCsvCell(section.title));
    lines.push(section.headers.map(escapeCsvCell).join(","));
    for (const row of section.rows) {
      lines.push(row.map(escapeCsvCell).join(","));
    }
  }
  const blob = new Blob(["\uFEFF" + lines.join("\n")], {
    type: "text/csv;charset=utf-8",
  });
  const name = opts.filename.endsWith(".csv") ? opts.filename : `${opts.filename}.csv`;
  triggerDownload(blob, name);
}

/** Çok sayfalı Excel: Özet + veri sayfaları. */
export function downloadExcelWorkbook(opts: {
  filename: string;
  meta: ExportMeta;
  sheets: SheetTable[];
}): void {
  const wb = XLSX.utils.book_new();
  const ozet = XLSX.utils.aoa_to_sheet(metaRows(opts.meta));
  ozet["!cols"] = [{ wch: 28 }, { wch: 48 }];
  XLSX.utils.book_append_sheet(wb, ozet, "Özet");

  for (const sheet of opts.sheets) {
    if (sheet.rows.length === 0 && sheet.headers.length === 0) continue;
    const aoa = [sheet.headers, ...sheet.rows.map((r) => r.map((c) => (c ?? "") as string | number))];
    const ws = XLSX.utils.aoa_to_sheet(aoa);
    ws["!cols"] = sheet.headers.map((h) => ({ wch: Math.min(Math.max(h.length + 2, 12), 36) }));
    const safeName = sheet.name.slice(0, 31) || "Sayfa";
    XLSX.utils.book_append_sheet(wb, ws, safeName);
  }

  const data = XLSX.write(wb, { bookType: "xlsx", type: "array" });
  const blob = new Blob([data], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  const name = opts.filename.endsWith(".xlsx") ? opts.filename : `${opts.filename}.xlsx`;
  triggerDownload(blob, name);
}

/** Geriye dönük basit CSV (tek tablo). */
export function downloadCsv(filename: string, headers: string[], rows: unknown[][]): void {
  downloadRichCsv({ filename, meta: {}, headers, rows });
}
