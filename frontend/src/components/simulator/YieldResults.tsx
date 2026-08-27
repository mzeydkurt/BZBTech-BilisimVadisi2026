import { ExternalLink } from "lucide-react";

import { ExactTermMatchWarning } from "@/components/simulator/ExactTermMatchWarning";
import { EvidenceText } from "@/components/common/EvidenceText";
import { Button } from "@/components/ui/button";
import { downloadExcelWorkbook, downloadRichCsv } from "@/lib/csv";
import { formatCurrencyTRY, formatPercent, parseDecimal } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ParticipationYieldResponse } from "@/types/api";

/**
 * ⚠️ `annual_yield_gross_pct` bankanın yayımladığı gerçekleşmiş getiridir;
 * `investor_share_pct` bu orana ZATEN dahildir — arayüzde getiriyle
 * ÇARPILMAZ, çarpılırsa pay iki kez düşülür. Yalnızca bilgi amaçlı gösterilir.
 */
export function YieldResults({
  result,
  onLadderSelect,
}: {
  result: ParticipationYieldResponse;
  /** Vade merdiveni: 30 / 90 / 180 / 360 gün. */
  onLadderSelect?: (termDays: number) => void;
}) {
  const isSingleSource = result.offers.length <= 1;
  const ladder = [30, 90, 180, 360];

  const exportData = (format: "csv" | "xlsx") => {
    const base = `katilma-getiri-simulasyon-${result.term_days}gun`;
    const depositNum = parseDecimal(result.deposit_try) ?? 0;
    const headers = [
      "Banka",
      "Ürün Adı",
      "Yıllık Brüt Getiri (%)",
      "Katılımcı Payı (%)",
      "Yatırılan Tutar (TL)",
      "Vade (Gün)",
      "Brüt Kâr Payı (TL)",
      "Stopaj Oranı (%)",
      "Stopaj Tutarı (TL)",
      "Net Kâr Payı (TL)",
      "Vade Sonu Toplam Tutar (TL)",
      "Kaynak URL",
    ];
    const rows = result.offers.map((o) => {
      const netProfit = parseDecimal(o.net_profit_try) ?? 0;
      const totalReturn = depositNum + netProfit;
      return [
        o.bank_name,
        o.product_name,
        parseDecimal(o.annual_yield_gross_pct) ?? o.annual_yield_gross_pct,
        parseDecimal(o.investor_share_pct ?? "") ?? (o.investor_share_pct ?? ""),
        depositNum,
        result.term_days,
        parseDecimal(o.gross_profit_try) ?? o.gross_profit_try,
        parseDecimal(o.withholding_pct) ?? o.withholding_pct,
        parseDecimal(o.withholding_try) ?? o.withholding_try,
        netProfit,
        totalReturn,
        o.source_url ?? "",
      ];
    });
    const meta = {
      "Simülasyon Türü": "Katılma Hesabı Getiri Simülasyonu",
      "Yatırılan Tutar": `${depositNum.toLocaleString("tr-TR")} TL`,
      "Vade (Gün)": result.term_days,
      "Para Birimi": result.currency,
      "Teklif Sayısı": result.offers.length,
      "Stopaj Açıklaması": result.withholding_note ?? "",
      "Hesaplama Yöntemi": result.method_note ?? "",
    };
    const missingSheet =
      result.banks_without_data.length > 0
        ? {
            name: "Veri Bulunamayan Bankalar",
            headers: ["Banka", "Neden"],
            rows: result.banks_without_data.map((b) => [b.bank_name, b.reason]),
          }
        : null;

    if (format === "csv") {
      downloadRichCsv({
        filename: `${base}.csv`,
        meta,
        headers,
        rows,
        extraSections: missingSheet
          ? [{ title: "Veri Bulunamayan Bankalar", headers: missingSheet.headers, rows: missingSheet.rows }]
          : [],
      });
      return;
    }

    downloadExcelWorkbook({
      filename: `${base}.xlsx`,
      meta,
      sheets: [
        { name: "Katılma Getiri Teklifleri", headers, rows },
        ...(missingSheet ? [missingSheet] : []),
      ],
    });
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-text-500">
            {isSingleSource ? "Tek Kaynak Sonucu" : "Sıralama"}
          </p>
          {onLadderSelect && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              <span className="mr-1 self-center text-xs text-text-500">Vade merdiveni:</span>
              {ladder.map((days) => (
                <button
                  key={days}
                  type="button"
                  onClick={() => onLadderSelect(days)}
                  className={cn(
                    "rounded-sm border px-2 py-0.5 text-xs transition-colors",
                    result.term_days === days
                      ? "border-brand-700 bg-teal-100 text-brand-900"
                      : "border-border text-text-700 hover:border-text-500",
                  )}
                >
                  {days} gün
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="flex gap-2">
          <Button type="button" variant="secondary" size="sm" onClick={() => exportData("csv")}>
            CSV indir
          </Button>
          <Button type="button" variant="secondary" size="sm" onClick={() => exportData("xlsx")}>
            Excel indir
          </Button>
        </div>
      </div>

      {result.offers.map((offer) => (
        <div
          key={offer.bank_code}
          className="rounded-lg border border-border bg-surface p-4"
        >
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-sm text-text-500">{offer.bank_name}</p>
              <p className="text-base font-semibold text-text-900">{offer.product_name}</p>
            </div>
            <div className="text-right">
              <p className="tabular text-2xl font-semibold text-brand-700">
                {formatPercent(offer.annual_yield_gross_pct)}
              </p>
              <p className="text-xs text-text-500">yıllık brüt getiri</p>
            </div>
          </div>

          {!offer.is_exact_term_match && (
            <div className="mt-2 flex items-center gap-1.5 text-sm text-text-500">
              <ExactTermMatchWarning ratePublishedForMonths={null} />
              Bu getiri {offer.rate_term_label ?? "farklı bir vade"} için yayımlanmıştır.
            </div>
          )}

          <div className="mt-3 grid grid-cols-2 gap-3 border-t border-border pt-3 text-sm sm:grid-cols-4">
            <div>
              <p className="text-text-500">Brüt Kâr Payı</p>
              <p className="tabular text-text-900">{formatCurrencyTRY(offer.gross_profit_try, 2)}</p>
            </div>
            <div>
              <p className="text-text-500">Stopaj ({formatPercent(offer.withholding_pct)})</p>
              <p className="tabular text-text-900">
                −{formatCurrencyTRY(offer.withholding_try, 2)}
              </p>
            </div>
            <div>
              <p className="text-text-500">Net Kâr Payı</p>
              <p className="tabular font-medium text-text-900">
                {formatCurrencyTRY(offer.net_profit_try, 2)}
              </p>
            </div>
            <div>
              <p className="text-text-500">Katılımcı Payı (bilgi amaçlı)</p>
              <p className="tabular text-text-900">{formatPercent(offer.investor_share_pct)}</p>
            </div>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
            {offer.source_url && (
              <a
                href={offer.source_url}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex items-center gap-1 font-medium text-brand-700 hover:text-brand-900"
              >
                Kaynak
                <ExternalLink className="h-3 w-3" aria-hidden="true" />
              </a>
            )}
            {offer.evidence_text && (
              <EvidenceText text={offer.evidence_text} className="text-text-500" />
            )}
          </div>
        </div>
      ))}

      {result.banks_without_data.length > 0 && (
        <div className="rounded-lg border border-dashed border-border bg-neutral-50 p-4">
          <h3 className="text-sm font-semibold text-text-500">
            Katılma getirisi yayımlamayan bankalar
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

      <p className="text-xs text-text-500">{result.withholding_note}</p>
      <p className="text-xs text-text-500">{result.method_note}</p>
    </div>
  );
}
