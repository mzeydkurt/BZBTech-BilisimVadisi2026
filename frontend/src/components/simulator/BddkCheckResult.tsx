import { AlertTriangle, CheckCircle2 } from "lucide-react";

import { formatCurrencyTRY, formatMonths, formatPercent } from "@/lib/format";
import type { BDDKLimitCheckResponse } from "@/types/api";

export function BddkCheckResult({ result }: { result: BDDKLimitCheckResponse }) {
  return (
    <div className="space-y-3 rounded-lg border border-border bg-surface p-4">
      <p className="text-xs text-text-500">{result.value_band_label}</p>

      {/* ⚠️ `is_financing_allowed: false` çıplak `0` olarak DEĞİL, açık cümle olarak gösterilir. */}
      {result.is_financing_allowed ? (
        <div className="flex items-start gap-2">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-brand-500" aria-hidden="true" />
          <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
            <div>
              <p className="text-text-500">Azami Finansman Oranı</p>
              <p className="tabular text-lg font-semibold text-text-900">
                {formatPercent(result.max_financing_ratio_pct, { decimals: 0 })}
              </p>
            </div>
            <div>
              <p className="text-text-500">Azami Finansman Tutarı</p>
              <p className="tabular text-lg font-semibold text-text-900">
                {formatCurrencyTRY(result.max_financing_amount_try)}
              </p>
            </div>
            <div>
              <p className="text-text-500">Azami Vade</p>
              <p className="tabular text-lg font-semibold text-text-900">
                {formatMonths(result.max_allowed_term_months)}
              </p>
            </div>
          </div>
        </div>
      ) : (
        <div className="flex items-start gap-2">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger-600" aria-hidden="true" />
          <p className="text-sm font-medium text-danger-600">
            Bu değerdeki varlık için BDDK sınırları çerçevesinde finansman kullandırılmasına izin
            verilmiyor.
          </p>
        </div>
      )}

      {result.energy_class && (
        <p className="text-xs text-text-500">Enerji sınıfı grubu: {result.energy_class}</p>
      )}

      <p className="border-t border-border pt-2 text-xs text-text-500">{result.legal_reference}</p>
    </div>
  );
}
