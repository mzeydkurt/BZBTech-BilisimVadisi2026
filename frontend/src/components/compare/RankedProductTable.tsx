import { ExternalLink } from "lucide-react";

import { MissingValue } from "@/components/common/MissingValue";
import { RateTypeBadge } from "@/components/products/RateTypeBadge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatMonths, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { RankedProduct } from "@/types/api";

export function RankedProductTable({ items, winnerId }: { items: RankedProduct[]; winnerId?: number }) {
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-surface">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-neutral-50">
            <TableHead className="w-10 text-right">#</TableHead>
            <TableHead>Ürün</TableHead>
            <TableHead className="w-40">Banka</TableHead>
            <TableHead className="w-32">Oran Türü</TableHead>
            <TableHead className="text-right">Oran</TableHead>
            <TableHead className="text-right">Vade</TableHead>
            <TableHead className="w-10" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item, index) => (
            <TableRow
              // ⚠️ Aynı ürün varyantı birden çok satırda görünebilir (ör. farklı
              // vadelerde ayrı sıralanmış); `product_id` tek başına eşsiz DEĞİLDİR.
              key={`${item.product_id}-${item.rank ?? index}`}
              className={cn(item.product_id === winnerId && "bg-teal-100/40")}
            >
              <TableCell className="tabular text-right text-text-500">{item.rank}</TableCell>
              <TableCell className="font-medium text-text-900">{item.product_name}</TableCell>
              <TableCell className="text-text-500">{item.bank_name}</TableCell>
              <TableCell>
                <RateTypeBadge rateType={item.rate_type} />
              </TableCell>
              <TableCell className="tabular text-right text-text-900">
                <MissingValue value={item.profit_rate_pct} format={formatPercent} />
              </TableCell>
              <TableCell className="tabular text-right text-text-500">
                {formatMonths(item.term_months)}
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
