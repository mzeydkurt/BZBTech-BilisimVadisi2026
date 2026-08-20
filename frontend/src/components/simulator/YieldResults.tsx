import { ExactTermMatchWarning } from "@/components/simulator/ExactTermMatchWarning";
import { formatCurrencyTRY, formatPercent } from "@/lib/format";
import type { ParticipationYieldResponse } from "@/types/api";

/**
 * ⚠️ `annual_yield_gross_pct` bankanın yayımladığı gerçekleşmiş getiridir;
 * `investor_share_pct` bu orana ZATEN dahildir — arayüzde getiriyle
 * ÇARPILMAZ, çarpılırsa pay iki kez düşülür. Yalnızca bilgi amaçlı gösterilir.
 */
export function YieldResults({ result }: { result: ParticipationYieldResponse }) {
  const isSingleSource = result.offers.length <= 1;

  return (
    <div className="space-y-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-text-500">
        {isSingleSource ? "Tek Kaynak Sonucu" : "Sıralama"}
      </p>

      {result.offers.map((offer) => (
        <div
          key={offer.bank_code}
          className="rounded-lg border border-border bg-surface p-4"
        >
          <div className="flex items-center justify-between">
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
