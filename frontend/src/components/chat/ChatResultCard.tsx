import { ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { formatPercent } from "@/lib/format";
import { taxonomyLabel } from "@/lib/taxonomy";
import type { ChatProductItem, ChatResultItem } from "@/types/api";

function metricRate(item: ChatResultItem): string | null {
  const rate = item.metrics.find((m) => m.field === "profit_rate_pct");
  return rate?.value ?? null;
}

export function ChatResultCard({ item }: { item: ChatResultItem }) {
  const rate = metricRate(item);
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs text-text-500">{item.bank_name}</p>
          <p className="text-sm font-semibold text-text-900">{item.title}</p>
          <p className="mt-0.5 text-xs text-text-500">Durum: {taxonomyLabel(item.status)}</p>
        </div>
        {rate !== null && (
          <span className="tabular shrink-0 text-sm font-medium text-brand-700">
            {formatPercent(rate)}
          </span>
        )}
      </div>

      {item.summary && <p className="mt-2 text-sm text-text-900">{item.summary}</p>}

      <p className="mt-2 line-clamp-3 text-xs text-text-500">“{item.card_text}”</p>

      {item.channels.length > 0 && (
        <p className="mt-1 text-[11px] text-text-500">Kanallar: {item.channels.join(", ")}</p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {item.source_url && (
          <a
            href={item.source_url}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1.5 text-xs font-medium text-brand-700 hover:text-brand-900"
          >
            Kaynağı gör
            <ExternalLink className="h-3 w-3" aria-hidden="true" />
          </a>
        )}
        <Button asChild variant="secondary" size="sm" className="h-7 text-xs">
          <Link to={`/compare?bank=${item.bank_code}`}>Karşılaştırmaya ekle</Link>
        </Button>
      </div>
    </div>
  );
}

export function ChatProductCard({ item }: { item: ChatProductItem }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <p className="text-xs text-text-500">{item.bank_name}</p>
      <p className="text-sm font-semibold text-text-900">{item.product_name}</p>
      {item.rate_type && (
        <p className="mt-0.5 text-xs text-text-500">Oran türü: {item.rate_type}</p>
      )}
      {item.profit_rate_pct !== null && (
        <p className="mt-1 text-sm text-brand-700">{formatPercent(item.profit_rate_pct)}</p>
      )}
      <p className="mt-2 line-clamp-3 text-xs text-text-500">“{item.card_text}”</p>
      <div className="mt-3">
        <Button asChild variant="secondary" size="sm" className="h-7 text-xs">
          <Link
            to={`/compare?bank=${item.bank_code}${item.rate_type ? `&rate_type=${item.rate_type}` : ""}`}
          >
            Karşılaştırmaya ekle
          </Link>
        </Button>
      </div>
    </div>
  );
}
