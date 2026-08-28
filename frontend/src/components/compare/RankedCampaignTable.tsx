import { ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";

import { BankLogo } from "@/components/common/BankLogo";
import { MissingValue } from "@/components/common/MissingValue";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatCurrencyTRY, formatDate, formatMonths, formatPercent } from "@/lib/format";
import { taxonomyLabel } from "@/lib/taxonomy";
import { cn } from "@/lib/utils";
import type { RankedCampaign } from "@/types/api";

export function RankedCampaignTable({
  items,
  winnerId,
  criterion,
  logoOnly = false,
}: {
  items: RankedCampaign[];
  winnerId?: number;
  criterion: string;
  logoOnly?: boolean;
}) {
  const showReward = criterion === "en_yuksek_odul" || items.some((i) => i.reward_amount_try);
  const showCashback =
    criterion === "en_yuksek_iade_orani" || items.some((i) => i.cashback_pct);
  const showDiscount =
    criterion === "en_yuksek_indirim" || items.some((i) => i.discount_pct);
  const showInstallments =
    criterion === "en_yuksek_taksit" || items.some((i) => i.installment_count != null);
  const showRate =
    criterion === "en_dusuk_kar_payi" || items.some((i) => i.profit_rate_pct);
  const showTerm =
    criterion === "en_uzun_vade" || items.some((i) => i.term_months_max != null);

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-surface">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-neutral-50">
            <TableHead className="w-10 text-right">#</TableHead>
            <TableHead>Kampanya</TableHead>
            <TableHead className="w-40">Banka</TableHead>
            <TableHead className="w-24">Durum</TableHead>
            {showReward && <TableHead className="text-right">Ödül</TableHead>}
            {showCashback && <TableHead className="text-right">İade</TableHead>}
            {showDiscount && <TableHead className="text-right">İndirim</TableHead>}
            {showInstallments && <TableHead className="text-right">Taksit</TableHead>}
            {showRate && <TableHead className="text-right">Oran</TableHead>}
            {showTerm && <TableHead className="text-right">Vade</TableHead>}
            <TableHead className="w-28">Bitiş</TableHead>
            <TableHead className="w-10" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item, index) => (
            <TableRow
              key={`${item.campaign_id}-${item.rank ?? index}`}
              className={cn(item.campaign_id === winnerId && "bg-teal-100/40")}
            >
              <TableCell className="tabular text-right text-text-500">{item.rank}</TableCell>
              <TableCell className="font-medium text-text-900">
                <Link
                  to={`/campaigns/${item.campaign_id}`}
                  className="hover:text-brand-700 hover:underline"
                >
                  {item.title}
                </Link>
              </TableCell>
              <TableCell>
                {logoOnly ? (
                  <BankLogo bankCode={item.bank_code} bankName={item.bank_name} size="sm" className="h-6 max-w-[105px]" />
                ) : (
                  <div className="flex items-center gap-2">
                    <BankLogo bankCode={item.bank_code} bankName={item.bank_name} size="sm" />
                    <span className="text-text-700">{item.bank_name}</span>
                  </div>
                )}
              </TableCell>
              <TableCell className="text-xs text-text-500">
                {taxonomyLabel(item.status)}
              </TableCell>
              {showReward && (
                <TableCell className="tabular text-right text-text-900">
                  <MissingValue
                    value={item.reward_amount_try}
                    format={(v) => formatCurrencyTRY(v, 0)}
                  />
                </TableCell>
              )}
              {showCashback && (
                <TableCell className="tabular text-right text-text-900">
                  <MissingValue value={item.cashback_pct} format={formatPercent} />
                </TableCell>
              )}
              {showDiscount && (
                <TableCell className="tabular text-right text-text-900">
                  <MissingValue value={item.discount_pct} format={formatPercent} />
                </TableCell>
              )}
              {showInstallments && (
                <TableCell className="tabular text-right text-text-900">
                  {item.installment_count ?? "—"}
                </TableCell>
              )}
              {showRate && (
                <TableCell className="tabular text-right text-text-900">
                  <MissingValue value={item.profit_rate_pct} format={formatPercent} />
                </TableCell>
              )}
              {showTerm && (
                <TableCell className="tabular text-right text-text-500">
                  {formatMonths(item.term_months_max)}
                </TableCell>
              )}
              <TableCell className="text-xs text-text-500">
                {formatDate(item.end_date)}
              </TableCell>
              <TableCell>
                {item.source_url && (
                  <a
                    href={item.source_url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-flex text-text-500 hover:text-brand-700"
                    aria-label={`${item.title} kaynağını aç`}
                  >
                    <ExternalLink className="h-4 w-4" aria-hidden="true" />
                  </a>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
