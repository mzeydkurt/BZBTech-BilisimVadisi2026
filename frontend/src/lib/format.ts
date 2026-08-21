/**
 * Türkçe yerelleştirilmiş biçimlendirme yardımcıları.
 *
 * Tüm `Intl`/yerel ayar çağrıları yalnızca bu dosyada yapılır; başka hiçbir
 * dosya doğrudan `toLocaleString`/`Intl` çağırmaz.
 */

export const NULL_PLACEHOLDER = "—";

const numberFormatter = new Intl.NumberFormat("tr-TR");
const dateFormatter = new Intl.DateTimeFormat("tr-TR", {
  day: "numeric",
  month: "short",
  year: "numeric",
});
const dateTimeFormatter = new Intl.DateTimeFormat("tr-TR", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

/** Backend'den string gelen Decimal'i sayıya çevirir; null güvenli. */
export function parseDecimal(value: string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number.parseFloat(value);
  return Number.isFinite(n) ? n : null;
}

/** Tamsayı/ondalık sayıyı Türkçe biçimde gösterir. `null`/`undefined` → "—". */
export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return NULL_PLACEHOLDER;
  }
  return numberFormatter.format(value);
}

/** ISO tarihi `"12 Oca 2026"` biçiminde gösterir. Geçersiz/boş → "—". */
export function formatDate(value: string | null | undefined): string {
  if (!value) return NULL_PLACEHOLDER;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return NULL_PLACEHOLDER;
  return dateFormatter.format(date);
}

/** ISO tarih-saati `"12 Oca 2026 14:30"` biçiminde gösterir. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return NULL_PLACEHOLDER;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return NULL_PLACEHOLDER;
  return dateTimeFormatter.format(date);
}

/** Serbest metin alanı; boşsa yedek değeri (varsayılan "—") gösterir. */
export function formatText(value: string | null | undefined, fallback = NULL_PLACEHOLDER): string {
  if (value === null || value === undefined || value === "") return fallback;
  return value;
}

interface FormatPercentOptions {
  /** Gösterilecek ondalık basamak sayısı. Varsayılan 2. */
  decimals?: number;
  /**
   * "points" (varsayılan): değer zaten yüzde puanı olarak gelir (3.05 → %3,05).
   * "unit": değer 0-1 birim aralığındadır, önce 100 ile çarpılır (0.85 → %85).
   */
  scale?: "points" | "unit";
}

/** Sayıyı ya da Decimal string'i Türkçe yüzde biçiminde gösterir: `"%2,05"`. */
export function formatPercent(
  value: number | string | null | undefined,
  opts: FormatPercentOptions = {},
): string {
  const { decimals = 2, scale = "points" } = opts;
  const n = typeof value === "string" ? parseDecimal(value) : value;
  if (n === null || n === undefined || !Number.isFinite(n)) return NULL_PLACEHOLDER;
  const scaled = scale === "unit" ? n * 100 : n;
  const formatted = new Intl.NumberFormat("tr-TR", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(scaled);
  return `%${formatted}`;
}

/**
 * TL tutarını `"500.000 ₺"` biçiminde gösterir. `Intl`'in yerleşik para birimi
 * stilini KULLANMAZ — o, sembolü başa koyar ve basamak sayısını 2'ye zorlar
 * (`"₺500.000,00"`), istenen çıktı bu değildir.
 */
export function formatCurrencyTRY(
  value: number | string | null | undefined,
  decimals = 0,
): string {
  const n = typeof value === "string" ? parseDecimal(value) : value;
  if (n === null || n === undefined || !Number.isFinite(n)) return NULL_PLACEHOLDER;
  const formatted = new Intl.NumberFormat("tr-TR", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n);
  return `${formatted} ₺`;
}

/** Ay sayısını `"12 ay"` biçiminde gösterir. */
export function formatMonths(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return NULL_PLACEHOLDER;
  }
  return `${numberFormatter.format(value)} ay`;
}

/** Ay aralığını `"1 - 36 ay"` biçiminde gösterir; tek uç varsa onu, ikisi de yoksa "—". */
export function formatMonthsRange(
  min: number | null | undefined,
  max: number | null | undefined,
): string {
  if (min === null || min === undefined) {
    return max === null || max === undefined ? NULL_PLACEHOLDER : formatMonths(max);
  }
  if (max === null || max === undefined || max === min) return formatMonths(min);
  return `${numberFormatter.format(min)} - ${formatMonths(max)}`;
}

/** Tutar aralığını `"500.000 - 2.000.000 ₺"` biçiminde gösterir; tek uç varsa onu, ikisi de yoksa "—". */
export function formatAmountRange(
  min: string | null | undefined,
  max: string | null | undefined,
): string {
  const minN = parseDecimal(min);
  const maxN = parseDecimal(max);
  if (minN === null) return maxN === null ? NULL_PLACEHOLDER : formatCurrencyTRY(maxN);
  if (maxN === null || maxN === minN) return formatCurrencyTRY(minN);
  return `${formatNumber(minN)} - ${formatCurrencyTRY(maxN)}`;
}
