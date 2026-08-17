import { ArrowDown, ArrowUp, ArrowUpDown, ExternalLink } from "lucide-react";

import { CategoryBadges } from "@/components/campaigns/CategoryBadges";
import { StatusBadge } from "@/components/campaigns/StatusBadge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDate, formatNumber, formatText } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { CampaignListItem, CampaignQuery } from "@/types/api";

type SortField = NonNullable<CampaignQuery["sort"]>;

interface CampaignTableProps {
  items: CampaignListItem[];
  sort: SortField;
  order: "asc" | "desc";
  onSortChange: (field: SortField) => void;
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  onRowClick?: (campaign: CampaignListItem) => void;
}

const COLUMNS: { key: SortField | null; label: string; className?: string }[] = [
  { key: "bank", label: "Banka", className: "w-40" },
  { key: "title", label: "Başlık" },
  { key: null, label: "Sektör", className: "w-44" },
  { key: null, label: "Ürün Türü", className: "w-40" },
  { key: null, label: "Segment", className: "w-28" },
  { key: "start_date", label: "Başlangıç", className: "w-28 text-right" },
  { key: "end_date", label: "Bitiş", className: "w-28 text-right" },
  { key: null, label: "Durum", className: "w-32" },
  { key: null, label: "Kaynak", className: "w-20 text-right" },
];

export function CampaignTable({
  items,
  sort,
  order,
  onSortChange,
  page,
  pageSize,
  total,
  totalPages,
  onPageChange,
  onRowClick,
}: CampaignTableProps) {
  const firstRow = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const lastRow = Math.min(page * pageSize, total);

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-surface">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-neutral-50">
            {COLUMNS.map((column) => (
              <TableHead key={column.label} className={column.className}>
                {column.key ? (
                  <button
                    type="button"
                    onClick={() => onSortChange(column.key as SortField)}
                    className="inline-flex items-center gap-1 rounded-sm transition-colors duration-150 hover:text-text-900"
                    aria-label={`${column.label} sütununa göre sırala`}
                  >
                    {column.label}
                    <SortIcon active={sort === column.key} order={order} />
                  </button>
                ) : (
                  column.label
                )}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>

        <TableBody>
          {items.map((campaign) => (
            <TableRow
              key={campaign.id}
              onClick={() => onRowClick?.(campaign)}
              className={cn(onRowClick && "cursor-pointer")}
            >
              <TableCell className="text-text-500">{campaign.bank_name}</TableCell>

              <TableCell className="font-medium text-text-900">
                {campaign.title}
                {/* Aynı sayfada birden çok kampanya varsa bu bilgi gizlenmez. */}
                {campaign.sub_campaign_count > 0 && (
                  <span className="ml-2 rounded border border-border px-1.5 py-0.5 text-xs font-normal text-text-500">
                    {campaign.sub_campaign_count} alt kampanya
                  </span>
                )}
              </TableCell>

              {/* Taksonomi backend'de üretilir; arayüz yalnızca gösterir. */}
              <TableCell className="text-text-500">
                <CategoryBadges categories={campaign.categories} axis="sector" max={2} />
              </TableCell>

              <TableCell className="text-text-500">
                <CategoryBadges categories={campaign.categories} axis="product_type" max={2} />
              </TableCell>

              <TableCell className="text-text-500">{formatText(campaign.segment)}</TableCell>

              {/* Sayısal/tarihsel kolonlar sağa hizalı ve tabular-nums (§10.2) */}
              <TableCell className="tabular text-right text-text-500">
                {formatDate(campaign.start_date)}
              </TableCell>

              <TableCell className="tabular text-right text-text-500">
                {formatDate(campaign.end_date)}
              </TableCell>

              <TableCell>
                <StatusBadge
                  status={campaign.status}
                  datePrecision={campaign.date_precision}
                  dateEvidence={campaign.date_evidence_text}
                />
              </TableCell>

              <TableCell className="text-right">
                <a
                  href={campaign.source_url}
                  target="_blank"
                  rel="noreferrer noopener"
                  onClick={(event) => event.stopPropagation()}
                  className="inline-flex items-center justify-center rounded-sm p-1 text-text-500 transition-colors duration-150 hover:text-brand-700"
                  aria-label={`${campaign.title} kampanyasının kaynak sayfasını yeni sekmede aç`}
                >
                  <ExternalLink className="h-4 w-4" aria-hidden="true" />
                </a>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-3 py-2">
        <p className="tabular text-sm text-text-500">
          {formatNumber(total)} kampanyanın {formatNumber(firstRow)}–{formatNumber(lastRow)} arası
        </p>

        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            disabled={page <= 1}
            onClick={() => onPageChange(page - 1)}
          >
            Önceki
          </Button>

          <span className="tabular text-sm text-text-500">
            {formatNumber(page)} / {formatNumber(Math.max(totalPages, 1))}
          </span>

          <Button
            variant="secondary"
            size="sm"
            disabled={page >= totalPages}
            onClick={() => onPageChange(page + 1)}
          >
            Sonraki
          </Button>
        </div>
      </div>
    </div>
  );
}

function SortIcon({ active, order }: { active: boolean; order: "asc" | "desc" }) {
  if (!active) return <ArrowUpDown className="h-3 w-3 opacity-40" aria-hidden="true" />;
  return order === "asc" ? (
    <ArrowUp className="h-3 w-3 text-brand-700" aria-hidden="true" />
  ) : (
    <ArrowDown className="h-3 w-3 text-brand-700" aria-hidden="true" />
  );
}
