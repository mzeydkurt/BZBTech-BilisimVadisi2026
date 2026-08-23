import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatCurrencyTRY, formatMonths, formatPercent, formatText } from "@/lib/format";
import type { ProductLimitOut } from "@/types/api";

const EXTRACTION_METHOD_LABELS: Record<string, string> = {
  html_table: "Statik oran tablosu",
  pdf_table: "PDF tablosu",
  text: "Metinden çıkarım",
};

export function ProductLimitTable({ limits }: { limits: ProductLimitOut[] }) {
  if (limits.length === 0) {
    return null;
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-surface">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-neutral-50">
            <TableHead>Varlık Değeri</TableHead>
            <TableHead className="text-right">Finansman Oranı</TableHead>
            <TableHead className="text-right">Vade Aralığı</TableHead>
            <TableHead className="text-right">Azami Tutar</TableHead>
            <TableHead>Enerji Sınıfı</TableHead>
            <TableHead className="w-40">Kaynak</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {limits.map((limit) => (
            <TableRow key={limit.id}>
              <TableCell className="tabular text-text-900">
                {limit.asset_value_min || limit.asset_value_max
                  ? `${formatCurrencyTRY(limit.asset_value_min)} – ${formatCurrencyTRY(limit.asset_value_max)}`
                  : "—"}
              </TableCell>
              <TableCell className="tabular text-right font-medium text-text-900">
                {formatPercent(limit.financing_ratio_pct, { decimals: 0 })}
              </TableCell>
              <TableCell className="tabular text-right text-text-500">
                {limit.term_months_min || limit.term_months_max
                  ? `${formatMonths(limit.term_months_min)} – ${formatMonths(limit.term_months_max)}`
                  : "—"}
              </TableCell>
              <TableCell className="tabular text-right text-text-500">
                {formatCurrencyTRY(limit.amount_max)}
              </TableCell>
              <TableCell className="text-text-500">{formatText(limit.energy_class)}</TableCell>
              <TableCell>
                {limit.evidence_text ? (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span
                        className="cursor-help text-xs text-text-500 underline decoration-dotted"
                        tabIndex={0}
                      >
                        {EXTRACTION_METHOD_LABELS[limit.extraction_method] ?? limit.extraction_method}
                      </span>
                    </TooltipTrigger>
                    <TooltipContent>“{limit.evidence_text}”</TooltipContent>
                  </Tooltip>
                ) : (
                  <span className="text-xs text-text-500">
                    {EXTRACTION_METHOD_LABELS[limit.extraction_method] ?? limit.extraction_method}
                  </span>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
