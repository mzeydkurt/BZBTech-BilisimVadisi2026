import { Fragment } from "react";

import { EvidenceText } from "@/components/common/EvidenceText";
import { RateTypeBadge } from "@/components/products/RateTypeBadge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatCurrencyTRY, formatDate, formatMonths, formatPercent } from "@/lib/format";
import type { ProductRateOut } from "@/types/api";

const RATE_SOURCE_LABELS: Record<string, string> = {
  html_table: "Tablo",
  pdf_table: "PDF",
  payment_plan_derived: "Ödeme planı",
  calculator_api: "Hesaplayıcı API",
  calculator_playwright: "Hesaplayıcı",
  seed_manual: "Elle doğrulanmış",
  text: "Metin",
};

export function ProductRateTable({ rates }: { rates: ProductRateOut[] }) {
  if (rates.length === 0) {
    return (
      <p className="text-sm text-text-500">
        Bu ürün için yayımlanmış bir oran kaydı yok — oranlar varyantlarda olabilir.
      </p>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-surface">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-neutral-50">
            <TableHead>Oran Türü</TableHead>
            <TableHead className="text-right">Oran</TableHead>
            <TableHead className="text-right">Tahsis ücreti/oranı</TableHead>
            <TableHead className="text-right">Yıllık Maliyet</TableHead>
            <TableHead className="text-right">Vade</TableHead>
            <TableHead className="text-right">Tutar Aralığı</TableHead>
            <TableHead className="w-24 text-right">Tarih</TableHead>
            <TableHead className="w-28">Kaynak</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rates.map((rate) => (
            <Fragment key={rate.id}>
              <TableRow>
                <TableCell>
                  <RateTypeBadge rateType={rate.rate_type} />
                </TableCell>
                <TableCell className="tabular text-right font-medium text-text-900">
                  {formatPercent(rate.profit_rate_pct)}
                </TableCell>
                <TableCell className="tabular text-right text-text-500">
                  {formatPercent(rate.allocation_fee_pct)}
                </TableCell>
                <TableCell className="tabular text-right text-text-500">
                  {formatPercent(rate.annual_cost_pct)}
                </TableCell>
                <TableCell className="tabular text-right text-text-500">
                  {rate.term_months !== null
                    ? formatMonths(rate.term_months)
                    : (rate.term_label ?? "—")}
                </TableCell>
                <TableCell className="tabular text-right text-text-500">
                  {rate.amount_min || rate.amount_max
                    ? `${formatCurrencyTRY(rate.amount_min)} – ${formatCurrencyTRY(rate.amount_max)}`
                    : "—"}
                </TableCell>
                <TableCell className="text-right text-xs text-text-500">
                  {formatDate(rate.effective_date)}
                </TableCell>
                <TableCell className="text-xs text-text-500">
                  <span className="rounded border border-border px-1.5 py-0.5">
                    {RATE_SOURCE_LABELS[rate.rate_source] ?? rate.rate_source}
                  </span>
                  {rate.is_binding === false && (
                    <span className="ml-1 text-warn-600">tahmini</span>
                  )}
                </TableCell>
              </TableRow>
              {rate.evidence_text && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={8} className="whitespace-pre-wrap pt-0 text-xs text-text-500">
                    <EvidenceText
                      text={rate.evidence_text}
                      prefix="Kaynak metin (birebir): "
                    />
                  </TableCell>
                </TableRow>
              )}
            </Fragment>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
