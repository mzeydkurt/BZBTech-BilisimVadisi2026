import { ExternalLink } from "lucide-react";

import { MissingValue } from "@/components/common/MissingValue";
import { RateTypeBadge } from "@/components/products/RateTypeBadge";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDate, formatMonths, formatPercent, formatText } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ComparableRateType, RankedProduct } from "@/types/api";

const RATE_SOURCE_LABELS: Record<string, string> = {
  html_table: "HTML tablo",
  pdf_table: "PDF tablo",
  text: "Metin",
  calculator_api: "Hesaplayıcı API",
  calculator_playwright: "Hesaplayıcı",
  payment_plan_derived: "Ödeme planı",
  js_default: "JS varsayılan",
  tkbb: "TKBB",
};

export function RankedProductTable({
  items,
  winnerId,
  rateType,
  showFeeColumns: showFeeColumnsProp,
}: {
  items: RankedProduct[];
  winnerId?: number;
  /** Oran türüne göre anlamsız kolonlar gizlenir. */
  rateType?: ComparableRateType | string;
  /** Geriye uyumluluk; `rateType` yoksa bu kullanılır. */
  showFeeColumns?: boolean;
}) {
  const showFeeColumns =
    showFeeColumnsProp !== undefined
      ? showFeeColumnsProp
      : !rateType || rateType === "financing_rate";
  const showShareColumns = rateType === "profit_sharing_ratio";
  const showTermLabel = rateType === "participation_yield" || rateType === "profit_sharing_ratio";

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-surface">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-neutral-50">
            <TableHead className="w-10 text-right">#</TableHead>
            <TableHead>Ürün</TableHead>
            <TableHead className="w-40">Banka</TableHead>
            <TableHead className="w-32">Oran Türü</TableHead>
            <TableHead className="text-right">
              {showShareColumns ? "Katılımcı payı" : "Oran"}
            </TableHead>
            {showFeeColumns && (
              <>
                <TableHead className="text-right">Tahsis ücreti/oranı</TableHead>
                <TableHead className="text-right">Yıllık Maliyet</TableHead>
              </>
            )}
            <TableHead className="text-right">Vade</TableHead>
            <TableHead className="w-36">Kanıt</TableHead>
            <TableHead className="w-10" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item, index) => (
            <TableRow
              key={`${item.product_id}-${item.rank ?? index}`}
              className={cn(item.product_id === winnerId && "bg-teal-100/40")}
            >
              <TableCell className="tabular text-right text-text-500">{item.rank}</TableCell>
              <TableCell className="font-medium text-text-900">
                <div>{item.product_name}</div>
                {(item.variant_label || item.account_tier) && (
                  <p className="mt-0.5 text-xs font-normal text-text-500">
                    {[item.variant_label, item.account_tier].filter(Boolean).join(" · ")}
                  </p>
                )}
              </TableCell>
              <TableCell className="text-text-500">{item.bank_name}</TableCell>
              <TableCell>
                <RateTypeBadge rateType={item.rate_type} />
              </TableCell>
              <TableCell className="tabular text-right text-text-900">
                <MissingValue
                  value={
                    showShareColumns ? item.investor_share_pct : item.profit_rate_pct
                  }
                  format={formatPercent}
                />
              </TableCell>
              {showFeeColumns && (
                <>
                  <TableCell className="tabular text-right text-text-500">
                    <MissingValue value={item.allocation_fee_pct} format={formatPercent} />
                  </TableCell>
                  <TableCell className="tabular text-right text-text-500">
                    <MissingValue value={item.annual_cost_pct} format={formatPercent} />
                  </TableCell>
                </>
              )}
              <TableCell className="tabular text-right text-text-500">
                {showTermLabel && item.term_label
                  ? formatText(item.term_label)
                  : formatMonths(item.term_months)}
              </TableCell>
              <TableCell>
                <div className="flex flex-wrap gap-1">
                  {item.effective_date && (
                    <Badge variant="neutral" title="Veri tarihi">
                      {formatDate(item.effective_date)}
                    </Badge>
                  )}
                  {item.rate_source && (
                    <Badge variant="neutral" title="Kaynak türü">
                      {RATE_SOURCE_LABELS[item.rate_source] ?? item.rate_source}
                    </Badge>
                  )}
                  {item.is_binding === false && (
                    <Badge variant="unknown">Bağlayıcı değil</Badge>
                  )}
                </div>
              </TableCell>
              <TableCell>
                {item.source_url && (
                  <a
                    href={item.source_url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-flex items-center justify-center text-text-500 hover:text-brand-700"
                    aria-label={`${item.product_name} kaynağını aç`}
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
