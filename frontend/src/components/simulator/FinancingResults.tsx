import { ChevronDown, ExternalLink, Info } from "lucide-react";
import { Fragment, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { ExactTermMatchWarning } from "@/components/simulator/ExactTermMatchWarning";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { downloadExcelWorkbook, downloadRichCsv } from "@/lib/csv";
import { formatCurrencyTRY, formatPercent, parseDecimal } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { BankFinancingOffer, FinancingSimulationResponse } from "@/types/api";

function InstallmentTable({ offer }: { offer: BankFinancingOffer }) {
  const rows = offer.installments ?? [];
  if (rows.length === 0) {
    return <p className="px-4 py-3 text-xs text-text-500">Taksit planı bu teklifte yok.</p>;
  }

  const hasBsmv = rows.some((r) => (parseDecimal(r.bsmv ?? "0") ?? 0) > 0);
  const hasKkdf = rows.some((r) => (parseDecimal(r.kkdf ?? "0") ?? 0) > 0);

  return (
    <div className="max-h-72 overflow-auto border-t border-border">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-neutral-50">
            <TableHead className="text-right">Ay</TableHead>
            <TableHead className="text-right">Taksit</TableHead>
            <TableHead className="text-right">Kâr Payı</TableHead>
            {hasBsmv && (
              <TableHead className="text-right">
                BSMV {offer.bsmv_rate_pct ? `(%${offer.bsmv_rate_pct})` : ""}
              </TableHead>
            )}
            {hasKkdf && (
              <TableHead className="text-right">
                KKDF {offer.kkdf_rate_pct ? `(%${offer.kkdf_rate_pct})` : ""}
              </TableHead>
            )}
            <TableHead className="text-right">Anapara</TableHead>
            <TableHead className="text-right">Kalan</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.month}>
              <TableCell className="tabular text-right text-text-500">{row.month}</TableCell>
              <TableCell className="tabular text-right font-medium">
                {formatCurrencyTRY(row.installment, 2)}
              </TableCell>
              <TableCell className="tabular text-right text-text-500">
                {formatCurrencyTRY(row.profit_share, 2)}
              </TableCell>
              {hasBsmv && (
                <TableCell className="tabular text-right text-text-500">
                  {formatCurrencyTRY(row.bsmv ?? "0", 2)}
                </TableCell>
              )}
              {hasKkdf && (
                <TableCell className="tabular text-right text-text-500">
                  {formatCurrencyTRY(row.kkdf ?? "0", 2)}
                </TableCell>
              )}
              <TableCell className="tabular text-right text-text-500">
                {formatCurrencyTRY(row.principal, 2)}
              </TableCell>
              <TableCell className="tabular text-right text-text-500">
                {formatCurrencyTRY(row.remaining_balance, 2)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export function FinancingResults({ result }: { result: FinancingSimulationResponse }) {
  const [expanded, setExpanded] = useState<string | null>(
    result.offers.find((o) => o.is_best_offer)?.bank_code ?? result.offers[0]?.bank_code ?? null,
  );

  const chartData = result.offers.map((offer) => ({
    bank_name: offer.bank_name,
    total: parseDecimal(offer.total_cost_try ?? offer.total_payment_try) ?? 0,
  }));

  const exportData = (format: "csv" | "xlsx") => {
    const base = `taksit-simulasyon-${result.term_months}ay`;
    const headers = [
      "Banka",
      "Ürün",
      "Kâr payı (%)",
      "BSMV (%)",
      "KKDF (%)",
      "Aylık taksit (TL)",
      "Toplam kâr payı (TL)",
      "Toplam BSMV (TL)",
      "Toplam KKDF (TL)",
      "Toplam ödeme (TL)",
      "Tahsis ücreti (TL)",
      "Toplam maliyet (TL)",
      "Yıllık maliyet (%)",
      "Kaynak URL",
    ];
    const rows = result.offers.map((o) => [
      o.bank_name,
      o.product_name,
      o.profit_rate_pct,
      o.bsmv_rate_pct ?? "0",
      o.kkdf_rate_pct ?? "0",
      o.monthly_payment_try,
      o.total_profit_try,
      o.total_bsmv_try ?? "0",
      o.total_kkdf_try ?? "0",
      o.total_payment_try,
      o.allocation_fee_try,
      o.total_cost_try,
      o.annual_cost_pct,
      o.source_url,
    ]);
    const meta = {
      Rapor: "Finansman taksit simülasyonu",
      "Vade (ay)": result.term_months,
      "Teklif sayısı": result.offers.length,
      Not: result.method_note ?? "",
    };
    const best = result.offers.find((o) => o.is_best_offer);
    const installments = best?.installments ?? [];
    const installmentSheet =
      installments.length > 0
        ? {
            name: "Taksit planı (en iyi)",
            headers: [
              "Ay",
              "Taksit (TL)",
              "Kâr payı (TL)",
              "BSMV (TL)",
              "KKDF (TL)",
              "Anapara (TL)",
              "Kalan (TL)",
            ],
            rows: installments.map((r) => [
              r.month,
              r.installment,
              r.profit_share,
              r.bsmv ?? "0",
              r.kkdf ?? "0",
              r.principal,
              r.remaining_balance,
            ]),
          }
        : null;
    const missingSheet =
      result.banks_without_data.length > 0
        ? {
            name: "Veri yok",
            headers: ["Banka", "Neden"],
            rows: result.banks_without_data.map((b) => [b.bank_name, b.reason]),
          }
        : null;

    if (format === "csv") {
      downloadRichCsv({
        filename: `${base}.csv`,
        meta: { ...meta, "En iyi teklif": best?.bank_name ?? "" },
        headers,
        rows,
        extraSections: [
          ...(installmentSheet
            ? [
                {
                  title: "Taksit planı (en iyi teklif)",
                  headers: installmentSheet.headers,
                  rows: installmentSheet.rows,
                },
              ]
            : []),
          ...(missingSheet
            ? [{ title: "Veri yok", headers: missingSheet.headers, rows: missingSheet.rows }]
            : []),
        ],
      });
      return;
    }

    downloadExcelWorkbook({
      filename: `${base}.xlsx`,
      meta: { ...meta, "En iyi teklif": best?.bank_name ?? "" },
      sheets: [
        { name: "Teklifler", headers, rows },
        ...(installmentSheet ? [installmentSheet] : []),
        ...(missingSheet ? [missingSheet] : []),
      ],
    });
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" size="sm" onClick={() => exportData("csv")}>
          CSV indir
        </Button>
        <Button type="button" variant="secondary" size="sm" onClick={() => exportData("xlsx")}>
          Excel indir
        </Button>
      </div>

      {chartData.length > 1 && (
        <div className="rounded-lg border border-border bg-surface p-4">
          <h3 className="text-sm font-semibold text-text-900">Toplam ödeme karşılaştırması</h3>
          <div className="mt-3" style={{ width: "100%", height: Math.max(chartData.length * 36, 180) }}>
            <ResponsiveContainer>
              <BarChart data={chartData} layout="vertical" margin={{ left: 8, right: 16 }}>
                <CartesianGrid horizontal={false} stroke="var(--border)" />
                <XAxis
                  type="number"
                  tick={{ fontSize: 11, fill: "var(--text-500)" }}
                  tickFormatter={(v: number) => formatCurrencyTRY(v, 0)}
                />
                <YAxis
                  type="category"
                  dataKey="bank_name"
                  width={120}
                  tick={{ fontSize: 11, fill: "var(--text-500)" }}
                />
                <Tooltip
                  formatter={(value: number) => formatCurrencyTRY(value, 2)}
                  contentStyle={{
                    border: "1px solid var(--border)",
                    borderRadius: 6,
                    fontSize: 12,
                  }}
                />
                <Bar
                  dataKey="total"
                  fill="var(--brand-500)"
                  radius={[0, 4, 4, 0]}
                  isAnimationActive={false}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      <div className="overflow-hidden rounded-lg border border-border bg-surface">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-neutral-50">
              <TableHead className="w-8" />
              <TableHead>Banka</TableHead>
              <TableHead className="text-right">Kâr Payı Oranı</TableHead>
              <TableHead className="text-right">Aylık Taksit</TableHead>
              <TableHead className="text-right">Tahsis</TableHead>
              <TableHead className="text-right">Toplam Maliyet</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {result.offers.map((offer) => {
              const open = expanded === offer.bank_code;
              return (
                <Fragment key={offer.bank_code}>
                  <TableRow
                    className={cn(offer.is_best_offer && "bg-teal-100/40")}
                  >
                    <TableCell>
                      <button
                        type="button"
                        className="rounded p-1 text-text-500 hover:text-text-900"
                        aria-expanded={open}
                        aria-label={`${offer.bank_name} taksit tablosu`}
                        onClick={() =>
                          setExpanded(open ? null : offer.bank_code)
                        }
                      >
                        <ChevronDown
                          className={cn(
                            "h-4 w-4 transition-transform",
                            open && "rotate-180",
                          )}
                          aria-hidden="true"
                        />
                      </button>
                    </TableCell>
                    <TableCell className="font-medium text-text-900">
                      {offer.bank_name}
                      {offer.is_best_offer && (
                        <span className="ml-2 rounded-sm bg-brand-500 px-1.5 py-0.5 text-xs font-medium text-white">
                          En uygun
                        </span>
                      )}
                      <p className="text-xs font-normal text-text-500">{offer.product_name}</p>
                    </TableCell>
                    <TableCell className="tabular text-right text-text-900">
                      {formatPercent(offer.profit_rate_pct)}
                    </TableCell>
                    <TableCell className="tabular text-right text-text-900">
                      {formatCurrencyTRY(offer.monthly_payment_try, 2)}
                    </TableCell>
                    <TableCell className="tabular text-right text-text-500">
                      {formatCurrencyTRY(offer.allocation_fee_try, 2)}
                    </TableCell>
                    <TableCell className="tabular text-right text-text-900">
                      {formatCurrencyTRY(
                        offer.total_cost_try ?? offer.total_payment_try,
                        2,
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        {!offer.is_exact_term_match && (
                          <ExactTermMatchWarning
                            ratePublishedForMonths={offer.rate_term_months}
                          />
                        )}
                        {offer.source_url && (
                          <a
                            href={offer.source_url}
                            target="_blank"
                            rel="noreferrer noopener"
                            className="text-text-500 hover:text-brand-700"
                            aria-label="Kaynak"
                          >
                            <ExternalLink className="h-4 w-4" aria-hidden="true" />
                          </a>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                  {open && (
                    <TableRow className="hover:bg-transparent">
                      <TableCell colSpan={7} className="bg-neutral-50 p-0">
                        {offer.evidence_text && (
                          <p className="border-t border-border px-4 py-2 text-xs text-text-500">
                            Kanıt: “{offer.evidence_text}”
                          </p>
                        )}
                        <InstallmentTable offer={offer} />
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              );
            })}
          </TableBody>
        </Table>
      </div>

      {result.banks_without_data.length > 0 && (
        <div className="rounded-lg border border-dashed border-border bg-neutral-50 p-4">
          <h3 className="text-sm font-semibold text-text-500">
            Oran yayımlamadığı için teklif üretilemeyen bankalar
          </h3>
          <ul className="mt-2 space-y-1">
            {result.banks_without_data.map((bank) => (
              <li key={bank.bank_code} className="text-sm text-text-500">
                <span className="font-medium text-text-900">{bank.bank_name}</span> — {bank.reason}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="rounded-lg border border-border bg-neutral-50 p-3.5 text-xs text-text-600">
        <div className="flex items-start gap-2.5">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" aria-hidden="true" />
          <div className="space-y-1">
            <p className="font-medium text-text-900">Tahsis Ücreti ve Maliyet Bilgilendirmesi</p>
            <p>
              Tahsis ücretleri bankadan bankaya azami olarak finansman tutarının binde beşi yani %0.50&apos;si olarak tahsil edilmektedir. Bankalar arası farklılıklar gösterebileceğinden hesaplamaya dahil edilmemiştir.
            </p>
            <p className="text-text-500">{result.method_note}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
