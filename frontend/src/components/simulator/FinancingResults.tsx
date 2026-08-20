import { ExactTermMatchWarning } from "@/components/simulator/ExactTermMatchWarning";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatCurrencyTRY, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { FinancingSimulationResponse } from "@/types/api";

export function FinancingResults({ result }: { result: FinancingSimulationResponse }) {
  return (
    <div className="space-y-4">
      <div className="overflow-hidden rounded-lg border border-border bg-surface">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-neutral-50">
              <TableHead>Banka</TableHead>
              <TableHead className="text-right">Kâr Payı Oranı</TableHead>
              <TableHead className="text-right">Aylık Taksit</TableHead>
              <TableHead className="text-right">Toplam Kâr Payı</TableHead>
              <TableHead className="text-right">Toplam Ödeme</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {result.offers.map((offer) => (
              <TableRow
                key={offer.bank_code}
                className={cn(offer.is_best_offer && "bg-teal-100/40")}
              >
                <TableCell className="font-medium text-text-900">
                  {offer.bank_name}
                  {offer.is_best_offer && (
                    <span className="ml-2 rounded-sm bg-brand-500 px-1.5 py-0.5 text-xs font-medium text-white">
                      En uygun
                    </span>
                  )}
                </TableCell>
                <TableCell className="tabular text-right text-text-900">
                  {formatPercent(offer.profit_rate_pct)}
                </TableCell>
                <TableCell className="tabular text-right text-text-900">
                  {formatCurrencyTRY(offer.monthly_payment_try, 2)}
                </TableCell>
                <TableCell className="tabular text-right text-text-500">
                  {formatCurrencyTRY(offer.total_profit_try, 2)}
                </TableCell>
                <TableCell className="tabular text-right text-text-500">
                  {formatCurrencyTRY(offer.total_payment_try, 2)}
                </TableCell>
                <TableCell>
                  {!offer.is_exact_term_match && (
                    <ExactTermMatchWarning ratePublishedForMonths={offer.rate_term_months} />
                  )}
                </TableCell>
              </TableRow>
            ))}
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

      <p className="text-xs text-text-500">{result.method_note}</p>
    </div>
  );
}
